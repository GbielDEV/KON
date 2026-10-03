"""
Tool Resolver and Multi-Step Planner for the KON Assistant.
Translates natural language requests into structured tool executions without
depending on rigid embedding comparisons or a closed catalog of 4 intents.
Supports multi-step chained actions, OpenJarvis LoopGuard, and optional external LLM integration.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from backend.ai.tool_registry import ToolRegistry, get_tool_registry
from backend.ai.loop_guard import LoopGuard, LoopVerdict
from backend.core.config import get_settings
from backend.core.logger import kon_logger


def normalize_text(text: str) -> str:
    """Normalizes accents, lowercases, and cleans extra whitespace while preserving path separators."""
    text = text.strip().lower()
    norm = unicodedata.normalize("NFD", text)
    cleaned = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    cleaned = re.sub(r"[^\w\s\./:\\\"'\-]", " ", cleaned)
    return " ".join(cleaned.split())


@dataclass
class ToolCall:
    """Single tool invocation step."""
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolPlan:
    """Execution plan containing one or more ordered tool calls."""
    raw_text: str
    steps: List[ToolCall] = field(default_factory=list)
    explanation: str = ""
    success: bool = True
    error: Optional[str] = None


class ToolResolver:
    """
    Translates Brazilian Portuguese spoken or typed phrases into a structured ToolPlan.
    Operates in two modes:
      1. Hybrid Local Semantic Resolver (Zero heavy dependencies, instant <1ms, 0 RAM overhead).
      2. External LLM Provider (OpenAI, Anthropic, Gemini, Ollama) if configured in .env.
    """

    # Multi-action split regex patterns
    SPLIT_PATTERNS = [
        r"\s+e\s+depois\s+",
        r"\s+e\s+em\s+seguida\s+",
        r"\s+e\s+logo\s+apos\s+",
        r"\s+depois\s+",
        r"\s+em\s+seguida\s+",
        r"\s+e\s+abra\s+",
        r"\s+e\s+entre\s+no\s+",
        r"\s+e\s+pesquise\s+",
        r"\s+e\s+crie\s+",
        r"\s+e\s+faça\s+",
        r"\s+e\s+faca\s+",
        r"\s+e\s+calcule\s+",
    ]

    # Application mappings
    APP_ALIASES = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "navegador": "chrome",
        "browser": "chrome",
        "internet": "chrome",
        "bloco de notas": "notepad",
        "notepad": "notepad",
        "calculadora": "calc",
        "calc": "calc",
        "vs code": "code",
        "vscode": "code",
        "code": "code",
        "visual studio code": "code",
    }

    # Folder mappings
    FOLDER_ALIASES = {
        "downloads": "Downloads",
        "download": "Downloads",
        "documentos": "Documents",
        "documento": "Documents",
        "area de trabalho": "Desktop",
        "desktop": "Desktop",
        "imagens": "Pictures",
        "fotos": "Pictures",
        "videos": "Videos",
        "musicas": "Music",
    }

    # Common web domain mappings
    WEB_SITES = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://www.github.com",
        "chatgpt": "https://chatgpt.com",
        "whatsapp": "https://web.whatsapp.com",
    }

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry or get_tool_registry()
        self.settings = get_settings()

    def resolve(self, user_text: str) -> ToolPlan:
        """
        Resolves spoken natural language into an executable ToolPlan.
        """
        if not user_text or not user_text.strip():
            return ToolPlan(raw_text="", steps=[], success=False, error="EMPTY_INPUT")

        raw_trimmed = user_text.strip()
        kon_logger.info(f"[PLANNER] Resolvendo comando: '{raw_trimmed}'")

        # 1. Check if external LLM provider is active and configured
        if self.settings.ai_provider not in ("none", "mock", "") and self.settings.ai_api_key:
            try:
                llm_plan = self._resolve_with_llm(raw_trimmed)
                if llm_plan and llm_plan.steps:
                    return llm_plan
            except Exception as exc:
                kon_logger.warning(f"[PLANNER] Provedor LLM falhou ({exc}). Recorrendo ao resolvedor local.")

        # 2. Local semantic resolver
        return self._resolve_local(raw_trimmed)

    def _split_compound_phrases(self, text: str) -> List[str]:
        """Splits multi-action phrases into sub-commands."""
        parts = [text]
        for pattern in self.SPLIT_PATTERNS:
            new_parts = []
            for part in parts:
                sub = re.split(pattern, part, flags=re.IGNORECASE)
                new_parts.extend([s.strip() for s in sub if s.strip()])
            parts = new_parts

        # If splitting happened, reconstruct valid sub-phrases
        if len(parts) > 1:
            reconstructed = []
            for i, p in enumerate(parts):
                p_norm = normalize_text(p)
                # If subsequent part lost verb prefix (e.g. "no youtube" or "25 vezes 8"), prepend context
                if i > 0 and not any(p_norm.startswith(v) for v in ("abra", "abrir", "entre", "va", "pesquise", "crie", "procure", "faca", "faça", "calcule", "digite", "pressione", "clique")):
                    if any(site in p_norm for site in self.WEB_SITES):
                        reconstructed.append(f"abra {p}")
                    elif "pasta" in p_norm or any(f in p_norm for f in self.FOLDER_ALIASES):
                        reconstructed.append(f"abra a pasta {p}")
                    elif any(op in p_norm for op in ("vezes", "mais", "menos", "dividido", "*", "/", "+", "-")):
                        reconstructed.append(f"faça {p}")
                    else:
                        reconstructed.append(p)
                else:
                    reconstructed.append(p)
            return reconstructed
        return [text]

    def _resolve_local(self, text: str) -> ToolPlan:
        """Rule-directed semantic parser that maps free natural language to tool schemas."""
        sub_phrases = self._split_compound_phrases(text)
        steps: List[ToolCall] = []

        for sub_text in sub_phrases:
            norm = normalize_text(sub_text)

            # -------------------------------------------------------------
            # A) SHUTDOWN & RESTART
            # -------------------------------------------------------------
            if any(k in norm for k in ("desligar o computador", "desligue o computador", "desligar pc", "desligue")):
                steps.append(ToolCall(tool="shutdown_system"))
                continue

            if any(k in norm for k in ("reiniciar o computador", "reinicie o computador", "reiniciar pc", "reinicie")):
                steps.append(ToolCall(tool="restart_system"))
                continue

            # -------------------------------------------------------------
            # B) SYSTEM TELEMETRY / INFO
            # -------------------------------------------------------------
            if any(k in norm for k in ("uso de memoria", "memoria ram", "quanto de ram", "memoria do computador")):
                steps.append(ToolCall(tool="system_info", arguments={"metric": "memory"}))
                continue

            if any(k in norm for k in ("uso de cpu", "processador", "uso do processador")):
                steps.append(ToolCall(tool="system_info", arguments={"metric": "cpu"}))
                continue

            if any(k in norm for k in ("que horas", "qual o horario", "qual a hora", "horas atuais", "horario", "que horas sao", "me diga as horas", "diga as horas")):
                steps.append(ToolCall(tool="system_info", arguments={"metric": "time"}))
                continue

            if any(k in norm for k in ("status do sistema", "informacoes do sistema", "telemetria", "como esta o sistema", "uptime")):
                steps.append(ToolCall(tool="system_info", arguments={"metric": "all"}))
                continue

            # -------------------------------------------------------------
            # C) SCREENSHOT
            # -------------------------------------------------------------
            if any(k in norm for k in ("print da tela", "tire um print", "tirar print", "screenshot", "captura de tela", "capturar tela")):
                steps.append(ToolCall(tool="take_screenshot"))
                continue

            # -------------------------------------------------------------
            # D) WINDOW STATE & CLOSE APPLICATION
            # -------------------------------------------------------------
            if any(k in norm for k in ("maximize a janela", "maximize essa janela", "maximizar janela", "maximizar a janela")):
                steps.append(ToolCall(tool="maximize_window"))
                continue

            if any(k in norm for k in ("minimize a janela", "minimize essa janela", "minimizar janela", "minimizar a janela")):
                steps.append(ToolCall(tool="minimize_window"))
                continue

            if any(k in norm for k in ("restaure a janela", "restaurar janela", "restaure essa janela")):
                steps.append(ToolCall(tool="restore_window"))
                continue

            if any(k in norm for k in ("feche a janela", "fechar janela", "feche essa janela")):
                steps.append(ToolCall(tool="close_window"))
                continue

            if norm.startswith(("feche o ", "fechar o ", "feche a ", "fechar a ", "feche ", "fechar ", "encerre ", "encerrar ")):
                target = norm.split(" ", 2)[-1].strip()
                for app_key, canonical in self.APP_ALIASES.items():
                    if app_key in target or target in app_key:
                        steps.append(ToolCall(tool="close_application", arguments={"application": canonical}))
                        break
                else:
                    steps.append(ToolCall(tool="close_application", arguments={"application": target}))
                continue

            # -------------------------------------------------------------
            # D.1) WINDOW SWITCH & FOCUS
            # -------------------------------------------------------------
            switch_prefixes = (
                "troque para o ", "troque para a ", "troque para ",
                "mude para o ", "mude para a ", "mude para ",
                "volte para o ", "volte para a ", "volte para ",
                "focar o ", "focar a ", "focar ", "foque o ", "foque a ", "foque "
            )
            if any(norm.startswith(p) for p in switch_prefixes):
                for p in switch_prefixes:
                    if norm.startswith(p):
                        target = norm[len(p):].strip()
                        canonical = self.APP_ALIASES.get(target, target)
                        steps.append(ToolCall(tool="switch_window", arguments={"target": canonical}))
                        break
                continue

            # -------------------------------------------------------------
            # D.2) BROWSER TABS & NAVIGATION
            # -------------------------------------------------------------
            if any(k in norm for k in ("abra uma nova aba", "nova aba", "abrir nova aba", "abrir uma aba")):
                steps.append(ToolCall(tool="new_browser_tab"))
                continue
            if any(k in norm for k in ("feche a aba", "fechar a aba", "fechar aba", "feche essa aba")):
                steps.append(ToolCall(tool="close_browser_tab"))
                continue
            if any(k in norm for k in ("volte a pagina", "voltar a pagina", "volte para a pagina anterior", "pagina anterior")):
                steps.append(ToolCall(tool="browser_go_back"))
                continue
            if any(k in norm for k in ("avance a pagina", "avancar pagina", "proxima pagina")):
                steps.append(ToolCall(tool="browser_go_forward"))
                continue

            # -------------------------------------------------------------
            # D.3) KEYBOARD & TYPING
            # -------------------------------------------------------------
            if norm.startswith(("digite ", "digitar ", "escreva ", "escrever ")):
                for p in ("digite ", "digitar ", "escreva ", "escrever "):
                    if norm.startswith(p):
                        raw_typed = sub_text[len(p):].strip()
                        if (raw_typed.startswith('"') and raw_typed.endswith('"')) or (raw_typed.startswith("'") and raw_typed.endswith("'")):
                            raw_typed = raw_typed[1:-1]
                        steps.append(ToolCall(tool="type_text", arguments={"text": raw_typed}))
                        break
                continue

            if norm.startswith(("pressione ", "pressionar ", "aperte ", "apertar ", "tecle ", "teclar ")):
                for p in ("pressione ", "pressionar ", "aperte ", "apertar ", "tecle ", "teclar "):
                    if norm.startswith(p):
                        key_target = sub_text[len(p):].strip().lower()
                        if "+" in key_target or any(k in key_target for k in ("ctrl", "alt", "shift", "win")):
                            steps.append(ToolCall(tool="hotkey", arguments={"keys": key_target}))
                        else:
                            steps.append(ToolCall(tool="press_key", arguments={"key": key_target}))
                        break
                continue

            # -------------------------------------------------------------
            # D.4) MOUSE & SCROLLING
            # -------------------------------------------------------------
            if "role" in norm or "scroll" in norm or "rolar" in norm:
                if any(k in norm for k in ("baixo", "down")):
                    steps.append(ToolCall(tool="scroll", arguments={"amount": -4}))
                    continue
                elif any(k in norm for k in ("cima", "up")):
                    steps.append(ToolCall(tool="scroll", arguments={"amount": 4}))
                    continue

            if norm.startswith(("clique no botao ", "clique no ", "clique na ", "clique em ", "clique ")):
                if "botao direito" in norm:
                    steps.append(ToolCall(tool="right_click"))
                    continue
                elif "duplo clique" in norm:
                    steps.append(ToolCall(tool="double_click"))
                    continue
                for p in ("clique no botao ", "clique no ", "clique na ", "clique em "):
                    if norm.startswith(p):
                        target_el = sub_text[len(p):].strip()
                        steps.append(ToolCall(tool="click_element", arguments={"query": target_el}))
                        break
                else:
                    steps.append(ToolCall(tool="click"))
                continue

            # -------------------------------------------------------------
            # D.5) MATH CALCULATION / CALCULATOR INPUT
            # -------------------------------------------------------------
            if any(norm.startswith(p) for p in ("faca ", "faça ", "calcule ", "calcular ", "quanto e ", "quanto é ")):
                for p in ("faca ", "faça ", "calcule ", "calcular ", "quanto e ", "quanto é "):
                    if norm.startswith(p):
                        math_raw = norm[len(p):].strip()
                        math_expr = (
                            math_raw
                            .replace("multiplicado por", "*")
                            .replace("vezes", "*")
                            .replace("dividido por", "/")
                            .replace("dividido", "/")
                            .replace("mais", "+")
                            .replace("menos", "-")
                        )
                        clean_math = "".join(c for c in math_expr if c in "0123456789+-*/.()")
                        if clean_math:
                            steps.append(ToolCall(tool="type_text", arguments={"text": f"{clean_math}="}))
                            steps.append(ToolCall(tool="press_key", arguments={"key": "enter"}))
                        break
                if steps and steps[-1].tool in ("type_text", "press_key"):
                    continue

            # -------------------------------------------------------------
            # E) CREATE FOLDER ("cria uma pasta chamada Jogos dentro de Downloads", etc.)
            # -------------------------------------------------------------
            create_folder_match = re.search(
                r"(?:crie|criar|cria)\s+(?:uma\s+)?pasta\s+(?:chamada\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:dentro\s+de|em|na pasta)\s+([a-zA-Z0-9_\-\s]+))?$",
                norm
            )
            if create_folder_match:
                folder_name = create_folder_match.group(1).strip()
                parent_name = create_folder_match.group(2).strip() if create_folder_match.group(2) else "Downloads"
                # Resolve parent alias
                resolved_parent = self.FOLDER_ALIASES.get(parent_name, parent_name)
                steps.append(ToolCall(tool="create_folder", arguments={"name": folder_name.title(), "parent": resolved_parent}))
                continue

            # -------------------------------------------------------------
            # F) SEARCH FILE ("procure aquele arquivo PDF que criei ontem", "onde está o trabalho.pdf", etc.)
            # -------------------------------------------------------------
            search_prefixes = (
                "procure ", "procurar ", "busque ", "buscar ", "encontre ", "encontrar ",
                "ache ", "achar ", "onde esta ", "onde fica ", "cade o ", "cade a ", "cade "
            )
            if any(norm.startswith(prefix) for prefix in search_prefixes):
                raw_query = sub_text
                for prefix in search_prefixes:
                    if norm.startswith(prefix):
                        raw_query = sub_text[len(prefix):].strip()
                        break

                ext = None
                for candidate_ext in ("pdf", "txt", "docx", "xlsx", "png", "jpg", "zip", "mp3", "mp4"):
                    if candidate_ext in raw_query.lower():
                        ext = candidate_ext
                        break

                clean_query = raw_query.strip().strip('"').strip("'")
                for prefix_term in ("o arquivo ", "o documento ", "a pasta ", "aquele arquivo ", "meus "):
                    if clean_query.lower().startswith(prefix_term):
                        clean_query = clean_query[len(prefix_term):].strip()

                steps.append(ToolCall(tool="search_file", arguments={"query": clean_query or "documento", "extension": ext}))
                continue

            # -------------------------------------------------------------
            # G) WEB SEARCH / OPEN URL ("abra o youtube", "pesquise por X")
            # -------------------------------------------------------------
            if any(norm.startswith(p) for p in ("pesquise na internet por ", "pesquise por ", "pesquisar por ", "procure na web por ")):
                for p in ("pesquise na internet por ", "pesquise por ", "pesquisar por ", "procure na web por "):
                    if norm.startswith(p):
                        q = sub_text[len(p):].strip()
                        steps.append(ToolCall(tool="search_web", arguments={"query": q}))
                        break
                continue

            # Check direct known websites ("entre no youtube", "abra o youtube")
            found_website = False
            for site_key, site_url in self.WEB_SITES.items():
                if site_key == "google" and "chrome" in norm:
                    continue
                if site_key in norm:
                    steps.append(ToolCall(tool="open_url", arguments={"url": site_url}))
                    found_website = True
                    break
            if found_website:
                continue

            # -------------------------------------------------------------
            # H) OPEN FOLDER ("abra a pasta downloads", "abra documentos", "abra a pasta D:\...")
            # -------------------------------------------------------------
            if "pasta" in norm or "diretorio" in norm:
                found_f = False
                for pfx in ("abra a pasta ", "abra o diretorio ", "abrir a pasta ", "abrir o diretorio ", "abre a pasta ", "abre o diretorio "):
                    if norm.startswith(pfx):
                        folder_arg = sub_text[len(pfx):].strip()
                        steps.append(ToolCall(tool="open_folder", arguments={"folder": folder_arg}))
                        found_f = True
                        break

                if not found_f:
                    for f_key, f_canon in self.FOLDER_ALIASES.items():
                        if f_key in norm:
                            steps.append(ToolCall(tool="open_folder", arguments={"folder": f_canon}))
                            found_f = True
                            break
                if found_f:
                    continue

            # -------------------------------------------------------------
            # I) OPEN APPLICATION / FILE / FOLDER ("abra o chrome", "abra C:\...", "abra trabalho.pdf")
            # -------------------------------------------------------------
            for prefix in (
                "quero abrir o ", "quero abrir a ", "quero abrir ",
                "abra o ", "abra a ", "abra ",
                "abrir o ", "abrir a ", "abrir ",
                "inicie o ", "inicie a ", "inicie ",
                "iniciar o ", "iniciar a ", "iniciar ",
                "abre o ", "abre a ", "abre ", "executar "
            ):
                if norm.startswith(prefix):
                    target = norm[len(prefix):].strip()
                    raw_target = sub_text[len(prefix):].strip()

                    # Check if target is a direct folder path (e.g. "D:\Arquivos\Downloads")
                    is_direct_path = bool(re.match(r"^[a-zA-Z]:[\\/]", raw_target)) or "/" in raw_target or "\\" in raw_target
                    if is_direct_path:
                        try:
                            direct_p = Path(raw_target)
                            if direct_p.exists() and direct_p.is_dir():
                                steps.append(ToolCall(tool="open_folder", arguments={"folder": raw_target}))
                                break
                        except Exception:
                            pass

                    # Check if target is a file (has extension or starts with drive letter or has slashes)
                    has_ext = any(target.endswith(f".{e}") for e in ("pdf", "txt", "docx", "xlsx", "png", "jpg", "zip", "py", "mp3", "mp4"))
                    if has_ext or is_direct_path or "arquivo" in norm:
                        clean_file_target = raw_target
                        if clean_file_target.lower().startswith("arquivo "):
                            clean_file_target = clean_file_target[8:].strip()
                        steps.append(ToolCall(tool="open_file", arguments={"path": clean_file_target}))
                        break

                    # Check if target is a folder
                    if target in self.FOLDER_ALIASES:
                        steps.append(ToolCall(tool="open_folder", arguments={"folder": self.FOLDER_ALIASES[target]}))
                        break

                    # Check if target is an application
                    matched_app = None
                    for app_key, canonical in self.APP_ALIASES.items():
                        if app_key == target or app_key in target:
                            matched_app = canonical
                            break

                    if matched_app:
                        steps.append(ToolCall(tool="open_application", arguments={"application": matched_app}))
                    else:
                        steps.append(ToolCall(tool="open_application", arguments={"application": target}))
                    break
            else:
                # Standalone keyword detection (e.g. "chrome", "google chrome", "bloco de notas")
                matched_app = None
                for app_key, canonical in self.APP_ALIASES.items():
                    if norm == app_key:
                        matched_app = canonical
                        break
                if matched_app:
                    steps.append(ToolCall(tool="open_application", arguments={"application": matched_app}))

        if not steps:
            return ToolPlan(
                raw_text=text,
                steps=[],
                success=False,
                error="UNRESOLVED_COMMAND",
                explanation=f"Não consegui identificar ferramentas adequadas para o comando: '{text}'"
            )

        return ToolPlan(
            raw_text=text,
            steps=steps,
            success=True,
            explanation=f"Planejadas {len(steps)} ação(ões)."
        )

    def _resolve_with_llm(self, text: str) -> Optional[ToolPlan]:
        """
        Uses configured LLM provider (OpenAI, Anthropic, Ollama, etc.) to perform function calling.
        """
        # When an API key is present in .env, we construct an OpenAI-compatible function-calling request
        import urllib.request
        import json

        tools_schema = self.registry.export_openai_tools()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.ai_api_key}",
        }

        payload = {
            "model": self.settings.ai_model or "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Você é o orquestrador do assistente de voz KON. "
                        "Analise o comando do usuário e selecione as ferramentas apropriadas para executar a solicitação. "
                        "Responda chamando as funções necessárias."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "tools": tools_schema,
            "tool_choice": "auto",
        }

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls_data = message.get("tool_calls", [])

            steps: List[ToolCall] = []
            for tc in tool_calls_data:
                func = tc.get("function", {})
                tool_name = func.get("name")
                args = json.loads(func.get("arguments", "{}"))
                if tool_name and self.registry.has_tool(tool_name):
                    steps.append(ToolCall(tool=tool_name, arguments=args))

            if steps:
                return ToolPlan(raw_text=text, steps=steps, success=True)

        return None


class PlanExecutor:
    """
    Executes a ToolPlan step-by-step with OpenJarvis LoopGuard protection and permission checking.
    """

    def __init__(self, registry: Optional[ToolRegistry] = None, loop_guard: Optional[LoopGuard] = None) -> None:
        self.registry = registry or get_tool_registry()
        self.loop_guard = loop_guard or LoopGuard()

    def execute_plan(self, plan: ToolPlan) -> Dict[str, Any]:
        """
        Executes all steps in the plan and aggregates the final conversational result.
        """
        if not plan.success or not plan.steps:
            return {
                "success": False,
                "error": plan.error or "NO_STEPS",
                "message": "Desculpe, não consegui compreender como executar essa solicitação.",
                "step_results": [],
            }

        step_results = []
        speech_parts = []
        overall_success = True

        for index, step in enumerate(plan.steps):
            tool_name = step.tool
            args = step.arguments

            # 1. LoopGuard check
            verdict: LoopVerdict = self.loop_guard.check_call(tool_name, args)
            if verdict.blocked:
                kon_logger.warning(f"[EXECUTOR] LoopGuard bloqueou o passo {index + 1}: {verdict.reason}")
                return {
                    "success": False,
                    "error": "LOOP_GUARD_BLOCKED",
                    "message": f"Operação interrompida por proteção de loop: {verdict.reason}",
                    "step_results": step_results,
                }

            # 2. Execute via registry
            kon_logger.info(f"[EXECUTOR] Executando passo {index + 1}/{len(plan.steps)}: {tool_name}({args})")
            exec_res = self.registry.execute_tool(tool_name, **args)
            step_results.append(exec_res)

            if not exec_res.get("success", False):
                overall_success = False
                speech_parts.append(exec_res.get("message") or f"Falha ao executar {tool_name}.")
                break
            else:
                resp_text = exec_res.get("response_text")
                if resp_text:
                    speech_parts.append(resp_text)

        # Combine speech responses naturally
        final_speech = " ".join(speech_parts).strip()
        if not final_speech:
            final_speech = "Comando executado com sucesso." if overall_success else "Ocorreu uma falha na execução."

        return {
            "success": overall_success,
            "message": final_speech,
            "plan": [s.__dict__ for s in plan.steps],
            "step_results": step_results,
        }
