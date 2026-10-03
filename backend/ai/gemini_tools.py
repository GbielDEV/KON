"""
Gemini Live API Tool Bridge for KON Assistant.
Converts ToolRegistry specs into Gemini Function Declarations (ADA V2 pattern),
enforces dynamic SAFE, CONFIRM, CRITICAL security verification, computes blast radius/impact,
manages user voice/HUD confirmation lifecycles, and logs audit events.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable
from google.genai import types

from backend.core.logger import kon_logger
from backend.ai.tool_registry import ToolRegistry, ToolSpec, get_tool_registry
from backend.security.confirmation_manager import get_confirmation_manager
from backend.security.audit_logger import get_audit_logger
from backend.computer.files import FileManager


def python_type_to_gemini_type(p_type: str) -> str:
    """Maps JSON/Python type strings to Gemini OpenAPI types."""
    t = p_type.lower().strip()
    if t in ("string", "str"):
        return "STRING"
    elif t in ("integer", "int"):
        return "INTEGER"
    elif t in ("number", "float"):
        return "NUMBER"
    elif t in ("boolean", "bool"):
        return "BOOLEAN"
    elif t in ("array", "list"):
        return "ARRAY"
    elif t in ("object", "dict"):
        return "OBJECT"
    return "STRING"


def convert_tool_spec_to_declaration(spec: ToolSpec) -> Dict[str, Any]:
    """
    Converts a KON ToolSpec into a Gemini Live function declaration dictionary.
    """
    properties: Dict[str, Any] = {}
    for param_name, param_meta in spec.parameters.items():
        if isinstance(param_meta, dict):
            raw_type = param_meta.get("type", "string")
            g_type = python_type_to_gemini_type(raw_type)
            prop: Dict[str, Any] = {
                "type": g_type,
                "description": param_meta.get("description", f"Parâmetro {param_name}"),
            }
            if g_type == "ARRAY":
                prop["items"] = {"type": "STRING"}
            if "enum" in param_meta:
                prop["enum"] = param_meta["enum"]
            properties[param_name] = prop
        else:
            properties[param_name] = {
                "type": "STRING",
                "description": f"Parâmetro {param_name}",
            }

    declaration = {
        "name": spec.name,
        "description": spec.description,
        "parameters": {
            "type": "OBJECT",
            "properties": properties,
        }
    }
    if spec.required_parameters:
        declaration["parameters"]["required"] = spec.required_parameters

    return declaration


class GeminiToolDispatcher:
    """
    Manages declarations and execution of function calls originating from Gemini Live API.
    Enforces KON security permissions (SAFE, CONFIRM, CRITICAL) with dynamic context assessment.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        on_confirmation_request: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_executing: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.registry = registry or get_tool_registry()
        self.on_confirmation_request = on_confirmation_request
        self.on_executing = on_executing
        self.confirmation_mgr = get_confirmation_manager()
        self.audit_logger = get_audit_logger()
        self._pending_confirmations: Dict[str, asyncio.Future] = {}

    def get_gemini_tools_config(self) -> List[Dict[str, Any]]:
        """
        Returns the tools list configuration for types.LiveConnectConfig.
        Includes google_search and function_declarations.
        """
        declarations = []
        for spec in self.registry.list_tools().values():
            declarations.append(convert_tool_spec_to_declaration(spec))

        return [
            {"google_search": {}},
            {"function_declarations": declarations},
        ]

    def resolve_confirmation(self, request_id: str, confirmed: bool) -> bool:
        """
        Resolves an outstanding user confirmation request by ID or active session.
        """
        success, token, msg = self.confirmation_mgr.resolve_confirmation(
            confirmation_id=request_id,
            approved=confirmed,
        )

        future = self._pending_confirmations.get(request_id)
        if future and not future.done():
            future.set_result(confirmed)

        return success

    def _assess_dynamic_risk(self, tool_name: str, args: Dict[str, Any]) -> tuple[str, str]:
        """
        Calculates dynamic risk level and contextual impact explanation.
        Returns: (risk_level, impact_summary)
        """
        base_perm = self.registry.check_permission(tool_name, **args)

        # Contextual Input Policy Check for mouse/keyboard simulated events
        from backend.security.input_policy import InputPolicy, SIMULATED_INPUT_TOOLS
        if tool_name in SIMULATED_INPUT_TOOLS:
            allowed, pol_decision, pol_reason = InputPolicy.evaluate(tool_name, args)
            if pol_decision == "DENY":
                return "DENY", pol_reason
            if pol_decision == "CONFIRM":
                return "CONFIRM", pol_reason

        if tool_name == "delete_file":
            target_path = args.get("path") or args.get("file") or ""
            impact = FileManager.calculate_deletion_impact(target_path)
            risk = impact.get("risk_level", "CONFIRM")
            summary = impact.get("impact_summary", f"Excluir arquivo ou pasta '{target_path}'.")
            return risk, summary

        if tool_name in ("shutdown_system", "restart_system"):
            action = "desligado" if tool_name == "shutdown_system" else "reiniciado"
            return "CRITICAL", f"O computador será {action}. Todos os aplicativos abertos serão encerrados."

        if tool_name == "close_application":
            app = args.get("application") or args.get("app") or "aplicativo"
            return "CONFIRM", f"Encerrar todos os processos em execução de '{app}'."

        if tool_name == "create_file":
            p = args.get("path") or "novo arquivo"
            return "CONFIRM", f"Criar novo arquivo em '{p}'."

        if tool_name == "create_folder":
            name = args.get("name") or "nova pasta"
            parent = args.get("parent") or "Downloads"
            return "CONFIRM", f"Criar nova pasta '{name}' em '{parent}'."

        if tool_name in ("move_file", "rename_file", "copy_file"):
            src = args.get("source") or args.get("path") or ""
            dest = args.get("destination") or args.get("new_name") or ""
            return "CONFIRM", f"Operação de arquivo: '{src}' -> '{dest}'."

        # Restricted application check (terminals, shells, admin utilities)
        if tool_name in ("open_application", "launch_application"):
            target = (args.get("application") or args.get("app") or args.get("app_name") or args.get("target") or "").lower().strip()
            from backend.computer.applications import ApplicationManager
            if (
                target in ApplicationManager.RESTRICTED_APPLICATIONS
                or any(r in target for r in ("powershell", "cmd", "terminal", "prompt", "regedit", "mmc", "pwsh", "wt"))
            ):
                return "CONFIRM", f"Abrir terminal ou utilitário administrativo do sistema ('{target}')."
            return "SAFE", f"Abrir '{target}' no sistema."

        # Contextual Mouse Click Risk Assessment (elevate to CONFIRM if targeting destructive UI elements)
        if tool_name in ("click", "click_element", "double_click", "triple_click"):
            text_values = []
            for k in ("target", "text", "description", "expected_window", "label", "title", "name"):
                v = args.get(k)
                if isinstance(v, str):
                    text_values.append(v)
            joined_text = " ".join(text_values).lower()
            destructive_keywords = (
                "excluir", "deletar", "apagar", "remover", "formatar",
                "uninstall", "desinstalar", "destroy", "wipe", "clean disk"
            )
            matched_kw = next((kw for kw in destructive_keywords if kw in joined_text), None)
            if matched_kw:
                target_desc = next((args.get(k) for k in ("target", "text", "description", "label", "title", "expected_window") if args.get(k)), "elemento destrutivo")
                return "CONFIRM", f"Ação de clique pode acionar exclusão ou alteração relevante ('{target_desc}')."
            return "SAFE", f"Clique de mouse na interface ({args.get('expected_window') or 'janela ativa'})."

        # Contextual Browser Risk Assessment (elevate to CONFIRM on sensitive actions: checkout, purchase, delete, password)
        if tool_name in ("browser_click", "browser_type"):
            submit_requested = bool(args.get("submit"))
            text_values = []
            for k in ("text", "name", "selector", "description", "target"):
                v = args.get(k)
                if isinstance(v, str):
                    text_values.append(v)
            joined_text = " ".join(text_values).replace("_", " ").replace("-", " ").lower()

            sensitive_keywords = (
                "comprar", "finalizar", "checkout", "purchase", "pagamento",
                "payment", "pagar", "buy", "order", "submeter pedido",
                "excluir", "delete", "remover", "apagar",
                "senha", "password", "cartao", "cartão", "credit card", "card", "cvv"
            )
            matched_sensitive = next((kw for kw in sensitive_keywords if kw in joined_text), None)
            if matched_sensitive or (submit_requested and any(kw in joined_text for kw in ("comprar", "checkout", "pagamento", "delete", "excluir"))):
                action_desc = args.get("name") or args.get("text") or "operação sensível"
                return "CONFIRM", f"Ação no navegador envolve operação sensível ('{action_desc}') e requer confirmação do usuário."
            return "SAFE", f"Ação de navegação no KON Browser ({tool_name})."

        if tool_name in ("browser_open", "browser_search", "browser_snapshot", "browser_go_back", "browser_reload"):
            return "SAFE", f"Navegação na sessão do navegador KON ({tool_name})."

        # Explicit SAFE operations: view, open, read, search, list
        if tool_name in ("open_file", "open_folder"):
            target = args.get("path") or args.get("folder") or ""
            return "SAFE", f"Abrir '{target}' no sistema."

        if tool_name in ("search_file", "search_folder", "check_file_exists", "check_path", "list_directory", "read_file"):
            q = args.get("query") or args.get("path") or ""
            return "SAFE", f"Consultar ou localizar '{q}' no sistema."

        # Default mapping from registry
        risk_map = {"allow": "SAFE", "ask": "CONFIRM", "critical": "CRITICAL", "deny": "DENY"}
        return risk_map.get(base_perm, "SAFE"), f"Executar {tool_name} com argumentos {args}."

    async def execute_function_calls(
        self,
        function_calls: List[Any],
    ) -> List[types.FunctionResponse]:
        """
        Executes an incoming batch of function calls from Gemini Live,
        enforcing security policies, impact analysis, confirmations, and audit logging.
        """
        responses: List[types.FunctionResponse] = []

        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}
            call_id = fc.id

            kon_logger.info(f"[TOOL_CALL] Gemini solicitou: '{tool_name}' com args: {tool_args} (ID: {call_id})")

            tool_spec = self.registry.get_tool(tool_name)
            if not tool_spec:
                kon_logger.warning(f"[TOOL_CALL] Ferramenta '{tool_name}' desconhecida.")
                self.audit_logger.log_event(
                    tool=tool_name,
                    arguments=tool_args,
                    risk_level="SAFE",
                    decision="DENY",
                    confirmation_required=False,
                    error=f"Ferramenta '{tool_name}' não existe no KON.",
                )
                responses.append(
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": f"Erro: Ferramenta '{tool_name}' não existe no KON."}
                    )
                )
                continue

            # Expected window validation and auto-fill for simulated input tools
            from backend.security.input_policy import SIMULATED_INPUT_TOOLS
            if tool_name in SIMULATED_INPUT_TOOLS:
                exp_win = tool_args.get("expected_window")
                from backend.computer.computer_use import ComputerUseService
                if not exp_win:
                    if (
                        ComputerUseService._last_observed_window
                        and (time.time() - ComputerUseService._last_observed_time <= ComputerUseService.OBSERVED_WINDOW_TTL)
                    ):
                        exp_win = ComputerUseService._last_observed_window.get("title") or ComputerUseService._last_observed_window.get("process")
                        tool_args["expected_window"] = exp_win
                        kon_logger.info(f"[SECURITY] expected_window preenchido automaticamente com observação recente: '{exp_win}'")
                    else:
                        err_msg = (
                            f"Erro de Segurança: O parâmetro 'expected_window' é obrigatório para ações de entrada simulada ('{tool_name}') "
                            "e nenhuma janela ativa foi observada recentemente (TTL 10s). "
                            "Chame a ferramenta 'get_active_window' primeiro para confirmar a janela em foco."
                        )
                        kon_logger.warning(f"[SECURITY] {err_msg}")
                        responses.append(
                            types.FunctionResponse(
                                id=call_id,
                                name=tool_name,
                                response={"result": err_msg}
                            )
                        )
                        continue

            # Dynamic Context Risk & Impact Assessment
            risk_level, impact_summary = self._assess_dynamic_risk(tool_name, tool_args)
            kon_logger.info(f"[SECURITY] Risco contextual para '{tool_name}': {risk_level}. Impacto: {impact_summary}")

            # 1. Denied tools
            if risk_level == "DENY":
                self.audit_logger.log_event(
                    tool=tool_name,
                    arguments=tool_args,
                    risk_level="DENY",
                    decision="DENY",
                    confirmation_required=False,
                    error=f"Bloqueado pela política de segurança: {impact_summary}",
                )
                responses.append(
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": f"Aviso de Segurança: Execução de '{tool_name}' bloqueada pela política de segurança: {impact_summary}"}
                    )
                )
                continue

            # 2. Confirmation required (CONFIRM or CRITICAL)
            auth_token: Optional[str] = None
            if risk_level in ("CONFIRM", "CRITICAL"):
                # Create a formal PendingConfirmation with expiration and impact
                pending_conf = self.confirmation_mgr.create_confirmation(
                    tool=tool_name,
                    arguments=tool_args,
                    impact_summary=impact_summary,
                    permission_level=risk_level,
                    timeout_seconds=30.0,
                )
                conf_id = pending_conf.confirmation_id

                confirmed = False
                if self.on_confirmation_request:
                    future = asyncio.get_running_loop().create_future()
                    self._pending_confirmations[conf_id] = future
                    pending_conf.future = future

                    try:
                        res = self.on_confirmation_request({
                            "id": conf_id,
                            "tool": tool_name,
                            "description": tool_spec.description,
                            "permission": risk_level,
                            "args": tool_args,
                            "impact": impact_summary,
                        })

                        if asyncio.iscoroutine(res):
                            res = await res

                        if isinstance(res, bool):
                            confirmed = res
                            self.confirmation_mgr.resolve_confirmation(conf_id, confirmed)
                        elif not future.done():
                            confirmed = await asyncio.wait_for(future, timeout=30.0)
                        else:
                            confirmed = future.result()
                    except asyncio.TimeoutError:
                        kon_logger.warning(f"[SECURITY] Tempo limite esgotado para confirmação de '{tool_name}' ({conf_id}).")
                        confirmed = False
                        self.confirmation_mgr.resolve_confirmation(conf_id, False)
                    finally:
                        self._pending_confirmations.pop(conf_id, None)
                else:
                    kon_logger.warning(f"[SECURITY] Nenhuma interface de confirmação configurada para '{tool_name}'.")
                    confirmed = False

                if not confirmed:
                    kon_logger.info(f"[SECURITY] Execução de '{tool_name}' negada/cancelada pelo usuário.")
                    self.audit_logger.log_event(
                        tool=tool_name,
                        arguments=tool_args,
                        risk_level=risk_level,
                        decision="CONFIRM",
                        confirmation_required=True,
                        user_confirmation=False,
                        error="Ação não autorizada pelo usuário.",
                    )
                    responses.append(
                        types.FunctionResponse(
                            id=call_id,
                            name=tool_name,
                            response={"result": "O usuário cancelou ou não autorizou a execução desta ação."}
                        )
                    )
                    continue

                # User approved! Retrieve single-use authorization token
                auth_token = pending_conf.authorization_token

            # Notify UI that tool is executing
            if self.on_executing:
                try:
                    self.on_executing(tool_name, tool_args)
                except Exception as e:
                    kon_logger.debug(f"[UI] Erro no callback on_executing: {e}")

            # Execute Tool with authorization token if confirmation was required
            try:
                raw_result = await asyncio.to_thread(
                    self.registry.execute_tool,
                    tool_name,
                    authorization_token=auth_token,
                    **tool_args
                )

                # Format response content
                if isinstance(raw_result, dict):
                    if raw_result.get("success"):
                        msg = raw_result.get("message") or raw_result.get("response_text") or str(raw_result.get("result", "Sucesso."))
                        result_text = f"Sucesso: {msg}"
                        err_text = None
                    else:
                        err = raw_result.get("error") or raw_result.get("message") or "Falha na execução."
                        result_text = f"Erro: {err}"
                        err_text = err
                else:
                    result_text = str(raw_result)
                    err_text = None

                kon_logger.info(f"[TOOL_RESULT] Resultado de '{tool_name}': {result_text}")

                # Record successful or failed audit log
                self.audit_logger.log_event(
                    tool=tool_name,
                    arguments=tool_args,
                    risk_level=risk_level,
                    decision="ALLOW" if risk_level == "SAFE" else "CONFIRM",
                    confirmation_required=(risk_level in ("CONFIRM", "CRITICAL")),
                    user_confirmation=True if risk_level in ("CONFIRM", "CRITICAL") else None,
                    execution_result=result_text,
                    error=err_text,
                )

                responses.append(
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": result_text}
                    )
                )

            except Exception as exc:
                kon_logger.error(f"[TOOL_ERROR] Exceção ao executar '{tool_name}': {exc}")
                self.audit_logger.log_event(
                    tool=tool_name,
                    arguments=tool_args,
                    risk_level=risk_level,
                    decision="ALLOW" if risk_level == "SAFE" else "CONFIRM",
                    confirmation_required=(risk_level in ("CONFIRM", "CRITICAL")),
                    user_confirmation=True if risk_level in ("CONFIRM", "CRITICAL") else None,
                    error=str(exc),
                )
                responses.append(
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": f"Erro interno ao executar a ferramenta {tool_name}: {exc}"}
                    )
                )

        return responses
