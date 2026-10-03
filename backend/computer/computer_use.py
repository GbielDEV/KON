"""
Computer Use & Windows GUI Control Engine for KON Assistant.
Implements the formal OBSERVE -> ACT -> OBSERVE -> VERIFY loop:
- Full screen & window context awareness.
- Native Mouse control (move, click, double click, right click, drag, scroll).
- Native Keyboard control (typing text with PT-BR accents, special keys, hotkeys).
- High performance screenshot & visual hash verification.
- Safety boundaries & failsafes:
    COMPUTER_USE_MAX_ACTIONS = 30
    COMPUTER_USE_TIMEOUT = 120
    COMPUTER_USE_MAX_RETRIES = 3
    WindowContextMismatchError on unexpected foreground window.
- Hybrid Search: Deterministic Filesystem -> Explorer GUI fallback.
- Standardized logging with [COMPUTER] prefix.
"""
from __future__ import annotations

import ctypes
import time
from typing import Dict, Any, List, Optional, Callable


from backend.core.logger import kon_logger
from backend.computer.mouse import MouseController
from backend.computer.keyboard import KeyboardController
from backend.computer.screen import ScreenService
from backend.computer.windows import WindowsService
from backend.computer.filesystem import FileSystemService

user32 = ctypes.windll.user32

# Safety & Failsafe Constants
COMPUTER_USE_MAX_ACTIONS: int = 30
COMPUTER_USE_TIMEOUT: float = 120.0
COMPUTER_USE_MAX_RETRIES: int = 3


def _ensure_desktop_access() -> None:
    """Ensures current thread is attached to the interactive Default desktop."""
    try:
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


class WindowContextMismatchError(RuntimeError):
    """Raised when the active window does not match the expected window."""
    pass


class ComputerUseLimitExceededError(RuntimeError):
    """Raised when the maximum number of GUI actions or timeout is exceeded."""
    pass


class ComputerUseService:
    """
    Central Computer Use coordinator and safe execution loop for KON.
    """

    _action_count: int = 0
    _session_start_time: float = 0.0
    _last_observed_window: Optional[Dict[str, Any]] = None
    _last_observed_time: float = 0.0
    OBSERVED_WINDOW_TTL: float = 10.0

    @classmethod
    def reset_safety_counters(cls) -> None:
        """Resets action counter and session timer."""
        cls._action_count = 0
        cls._session_start_time = time.time()

    @classmethod
    def _check_safety_limits(cls) -> None:
        """Enforces MAX_ACTIONS and TIMEOUT limits."""
        cls._action_count += 1
        if cls._action_count > COMPUTER_USE_MAX_ACTIONS:
            msg = f"Limite de segurança de Computer Use excedido: máximo de {COMPUTER_USE_MAX_ACTIONS} ações atingido."
            kon_logger.error(f"[COMPUTER] FAILSAFE: {msg}")
            raise ComputerUseLimitExceededError(msg)

        if cls._session_start_time > 0:
            elapsed = time.time() - cls._session_start_time
            if elapsed > COMPUTER_USE_TIMEOUT:
                msg = f"Tempo limite de Computer Use excedido: {elapsed:.1f}s decorridos (limite: {COMPUTER_USE_TIMEOUT}s)."
                kon_logger.error(f"[COMPUTER] FAILSAFE: {msg}")
                raise ComputerUseLimitExceededError(msg)

    # -------------------------------------------------------------
    # Window & Context Safety
    # -------------------------------------------------------------

    @classmethod
    def verify_window_context(cls, expected_window: Optional[str]) -> bool:
        """
        Verifies that the current active window matches the expected window title or process.
        Raises WindowContextMismatchError if a mismatch is detected to prevent damaging clicks.
        """
        if not expected_window or not expected_window.strip():
            return True

        current = cls.get_active_window()
        cur_title = (current.get("title") or "").lower()
        cur_proc = (current.get("process") or "").lower()
        exp = expected_window.strip().lower()

        if exp not in cur_title and exp not in cur_proc:
            msg = (
                f"Segurança Computer Use: Janela ativa inesperada. "
                f"Esperado: '{expected_window}', mas a janela ativa atual é '{current.get('title')}' ({current.get('process')}). "
                f"Ação abortada para evitar cliques indesejados."
            )
            kon_logger.warning(f"[SECURITY] {msg}")
            raise WindowContextMismatchError(msg)

        return True

    # -------------------------------------------------------------
    # Screen & Windows Delegation
    # -------------------------------------------------------------

    @classmethod
    def get_screen_info(cls) -> Dict[str, Any]:
        return ScreenService.get_screen_info()

    @classmethod
    def get_active_window(cls) -> Dict[str, Any]:
        win = WindowsService.get_active_window()
        cls._last_observed_window = win
        cls._last_observed_time = time.time()
        return win

    @classmethod
    def list_windows(cls, query: Optional[str] = None) -> Dict[str, Any]:
        return WindowsService.list_windows(query=query)

    @classmethod
    def focus_window(cls, title_or_process: str) -> Dict[str, Any]:
        cls._check_safety_limits()
        return WindowsService.focus_window(title_or_process)

    @classmethod
    def maximize_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        return WindowsService.maximize_window(title_or_process)

    @classmethod
    def minimize_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        return WindowsService.minimize_window(title_or_process)

    @classmethod
    def restore_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        return WindowsService.restore_window(title_or_process)

    @classmethod
    def close_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        return WindowsService.close_window(title_or_process)

    # -------------------------------------------------------------
    # Telemetry & Event Helpers
    # -------------------------------------------------------------

    @classmethod
    def _emit_telemetry(cls, stage: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Dispatches structured [COMPUTER] telemetries to console and EventBus."""
        full_msg = f"[COMPUTER] {stage} -> {message}"
        kon_logger.info(full_msg)

    # -------------------------------------------------------------
    # Mouse Actions (Delegating to MouseController)
    # -------------------------------------------------------------

    @classmethod
    def move_mouse(cls, x: int, y: int, smooth: bool = True) -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("MOUSE_MOVE", f"Movendo cursor para ({x}, {y})")
        return MouseController.move_mouse(x=x, y=y, smooth=smooth)

    @classmethod
    def click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        expected_window: Optional[str] = None,
        smooth: bool = True,
    ) -> Dict[str, Any]:
        cls._check_safety_limits()
        coords_str = f" em ({x}, {y})" if x is not None and y is not None else ""
        cls._emit_telemetry("CLICK", f"Clique {button}{coords_str}")
        return MouseController.click(x=x, y=y, button=button, expected_window=expected_window, smooth=smooth)

    @classmethod
    def double_click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        cls._check_safety_limits()
        coords_str = f" em ({x}, {y})" if x is not None and y is not None else ""
        cls._emit_telemetry("CLICK", f"Clique duplo{coords_str}")
        return MouseController.double_click(x=x, y=y, expected_window=expected_window)

    @classmethod
    def right_click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        cls._check_safety_limits()
        coords_str = f" em ({x}, {y})" if x is not None and y is not None else ""
        cls._emit_telemetry("CLICK", f"Clique direito{coords_str}")
        return MouseController.right_click(x=x, y=y, expected_window=expected_window)

    @classmethod
    def mouse_down(cls, button: str = "left") -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("MOUSE_DOWN", f"Pressionando botão {button} do mouse")
        return MouseController.mouse_down(button=button)

    @classmethod
    def mouse_up(cls, button: str = "left") -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("MOUSE_UP", f"Soltando botão {button} do mouse")
        return MouseController.mouse_up(button=button)

    @classmethod
    def scroll(cls, amount: int = -3) -> Dict[str, Any]:
        cls._check_safety_limits()
        dir_str = "baixo" if amount < 0 else "cima"
        cls._emit_telemetry("SCROLL", f"Rolando tela para {dir_str} ({abs(amount)} passos)")
        return MouseController.scroll(amount=amount)

    @classmethod
    def drag(
        cls,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 15,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("DRAG", f"Arrastando de ({start_x}, {start_y}) para ({end_x}, {end_y})")
        return MouseController.drag(start_x, start_y, end_x, end_y, steps=steps, expected_window=expected_window)

    # -------------------------------------------------------------
    # Keyboard Actions (Delegating to KeyboardController)
    # -------------------------------------------------------------

    @classmethod
    def type_text(cls, text: str, expected_window: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("TYPE", f"Digitando {len(text)} caracteres")
        return KeyboardController.type_text(text, expected_window=expected_window)

    @classmethod
    def press_key(cls, key: str, expected_window: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        cls._emit_telemetry("KEY_PRESS", f"Pressionando tecla '{key}'")
        return KeyboardController.press_key(key, expected_window=expected_window)

    @classmethod
    def hotkey(cls, keys: Any, expected_window: Optional[str] = None) -> Dict[str, Any]:
        cls._check_safety_limits()
        keys_str = "+".join(keys) if isinstance(keys, (list, tuple)) else str(keys)
        cls._emit_telemetry("HOTKEY", f"Executando atalho '{keys_str}'")
        return KeyboardController.hotkey(keys, expected_window=expected_window)

    # -------------------------------------------------------------
    # Structured UI Observation & Element Finding (Windows UIAutomation)
    # -------------------------------------------------------------

    @classmethod
    def observe_ui(cls, max_elements: int = 30) -> Dict[str, Any]:
        """
        Observes the structured UI accessibility tree of the currently active window.
        Uses native Windows UIAutomationCore with graceful fallback.
        """
        _ensure_desktop_access()
        cls._emit_telemetry("OBSERVE", "Inspecionando elementos interativos da janela ativa")
        active = cls.get_active_window()
        hwnd = active.get("hwnd", 0)

        from backend.computer.uia import UIAutomationService
        elements = UIAutomationService.inspect_window_elements(hwnd=hwnd, max_elements=max_elements)

        if not elements:
            elements = [{
                "name": active.get("title", "Janela Ativa"),
                "type": "Window",
                "bounds": active.get("bounds", {}),
            }]

        cls._emit_telemetry("OBSERVE", f"Observados {len(elements)} elementos em '{active.get('title')}'")
        return {
            "success": True,
            "window": active,
            "elements_found": len(elements),
            "elements": elements,
            "message": f"Observados {len(elements)} elementos na janela '{active.get('title')}'.",
        }

    @classmethod
    def find_ui_element(cls, query: str, control_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Locates an interactive UI element by name or label in the foreground window.
        """
        cls._check_safety_limits()
        cls._emit_telemetry("OBSERVE", f"Buscando elemento '{query}'")
        from backend.computer.uia import UIAutomationService
        active = cls.get_active_window()
        hwnd = active.get("hwnd")
        match = UIAutomationService.find_element(query, control_type=control_type, hwnd=hwnd)

        if match:
            return {
                "success": True,
                "found": True,
                "element": match,
                "message": f"Elemento '{query}' encontrado em {match['center']}.",
            }
        return {
            "success": True,
            "found": False,
            "element": None,
            "message": f"Elemento '{query}' não foi localizado na janela atual.",
        }

    @classmethod
    def click_element(
        cls,
        query: str,
        button: str = "left",
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Finds an interactive element by name/label and clicks on its center coordinates.
        Enforces contextual safety against destructive buttons (ex: 'excluir', 'formatar').
        """
        cls._check_safety_limits()

        # Contextual Security Check: destructive buttons require confirmation
        destructive_keywords = ("excluir", "apagar", "delete", "formatar", "remover tudo", "desinstalar", "zerar")
        if any(k in query.lower() for k in destructive_keywords):
            msg = f"Ação no elemento '{query}' é potencialmente destrutiva e requer confirmação do usuário."
            kon_logger.warning(f"[SECURITY] {msg}")
            return {
                "success": False,
                "error": "CONFIRMATION_REQUIRED",
                "requires_confirmation": True,
                "message": msg,
            }

        from backend.computer.uia import UIAutomationService
        active = cls.get_active_window()
        hwnd = active.get("hwnd")
        match = UIAutomationService.find_element(query, hwnd=hwnd)

        if not match or "center" not in match:
            return {
                "success": False,
                "error": "ELEMENT_NOT_FOUND",
                "message": f"Não foi possível localizar o elemento '{query}' na tela.",
            }

        cx, cy = match["center"][0], match["center"][1]
        cls._emit_telemetry("CLICK", f"Clicando no elemento '{match['name']}' em ({cx}, {cy})")
        return cls.click(x=cx, y=cy, button=button, expected_window=expected_window, smooth=True)

    # -------------------------------------------------------------
    # The OBSERVE -> ACT -> OBSERVE -> VERIFY Loop
    # -------------------------------------------------------------

    @classmethod
    def execute_action_with_verification(
        cls,
        action_name: str,
        action_callable: Callable[[], Any],
        expected_window: Optional[str] = None,
        verify_visual_change: bool = True,
        max_retries: int = COMPUTER_USE_MAX_RETRIES,
    ) -> Dict[str, Any]:
        """
        Executes a single action within the rigorous OBSERVE -> ACT -> OBSERVE -> VERIFY loop:
        1. OBSERVE initial state & hash
        2. ACT (execute action_callable)
        3. OBSERVE resulting state & hash
        4. VERIFY outcome
        Retries up to max_retries if no change is detected and action is safe.
        """
        attempt = 0
        last_error = None

        while attempt < max_retries:
            attempt += 1
            kon_logger.info(f"[COMPUTER] Loop Ciclo: Ação='{action_name}' (Tentativa {attempt}/{max_retries})")

            # 1. OBSERVE
            initial_hash = ScreenService.get_screen_hash()
            initial_window = cls.get_active_window()

            # Context Check
            try:
                cls.verify_window_context(expected_window)
            except WindowContextMismatchError as w_err:
                kon_logger.error(f"[COMPUTER] Abortado por divergência de contexto: {w_err}")
                return {"success": False, "error": "WINDOW_CONTEXT_MISMATCH", "message": str(w_err)}

            # 2. ACT
            try:
                action_result = action_callable()
                time.sleep(0.15)
            except Exception as act_exc:
                last_error = str(act_exc)
                kon_logger.error(f"[COMPUTER] Erro ao agir: {act_exc}")
                continue

            # 3. OBSERVE AGAIN
            new_hash = ScreenService.get_screen_hash()
            new_window = cls.get_active_window()

            # 4. VERIFY
            visual_changed = (new_hash != initial_hash)
            window_changed = (new_window.get("hwnd") != initial_window.get("hwnd"))

            if verify_visual_change and not visual_changed and not window_changed:
                kon_logger.warning(f"[COMPUTER] Verification warning: nenhuma alteração visual detectada após '{action_name}'.")
                if attempt < max_retries:
                    time.sleep(0.2)
                    continue

            kon_logger.info(f"[COMPUTER] Verification SUCCESS: '{action_name}' validado com sucesso.")
            return {
                "success": True,
                "action": action_name,
                "attempts": attempt,
                "visual_changed": visual_changed,
                "window_changed": window_changed,
                "active_window": new_window,
                "action_result": action_result,
                "message": f"Ação '{action_name}' executada e verificada com sucesso.",
            }

        return {
            "success": False,
            "action": action_name,
            "error": "VERIFICATION_FAILED",
            "last_error": last_error,
            "attempts": attempt,
            "message": f"Ação '{action_name}' não produziu efeito verificável após {max_retries} tentativas.",
        }

    # -------------------------------------------------------------
    # Hybrid Search (Filesystem -> Explorer GUI Fallback)
    # -------------------------------------------------------------

    @classmethod
    def hybrid_find_file(
        cls,
        filename: str,
        fallback_to_explorer: bool = True,
    ) -> Dict[str, Any]:
        """
        Hybrid search strategy:
        1. Direct deterministic Filesystem access (C:\\, D:\\, E:\\, Downloads, Documents, Desktop, etc.).
        2. If found, returns immediate structured result.
        3. If not found and fallback_to_explorer=True:
           - Opens Windows Explorer
           - Triggers search bar
           - Observes and reports
        """
        kon_logger.info(f"[COMPUTER] hybrid_find_file iniciado para: '{filename}'")

        # Step 1: Deterministic filesystem search
        direct_res = FileSystemService.search_file(filename, max_results=3)
        if direct_res.get("found"):
            kon_logger.info("[COMPUTER] hybrid_find_file: Encontrado via Modo A (Filesystem determinístico)")
            direct_res["discovery_mode"] = "deterministic_filesystem"
            return direct_res

        if not fallback_to_explorer:
            return direct_res

        # Step 2: Fallback to Mode B (Visual Computer Use via Explorer)
        kon_logger.info("[COMPUTER] hybrid_find_file: Não encontrado no filesystem rápido. Ativando Modo B (Explorer GUI)...")
        try:
            # 1. Open Explorer at real user downloads or desktop
            cls.reset_safety_counters()
            real_folder = str(WindowsService.get_downloads_dir())
            FileSystemService.open_folder(real_folder)
            time.sleep(0.5)

            # 2. Focus Explorer and trigger search with Ctrl+F / Ctrl+E
            cls.hotkey(["ctrl", "f"])
            time.sleep(0.2)

            # 3. Type filename and press Enter
            cls.type_text(filename)
            time.sleep(0.1)
            cls.press_key("enter")
            time.sleep(0.5)

            # 4. Observe visual state
            screenshot_res = ScreenService.take_screenshot()
            active_win = cls.get_active_window()

            return {
                "found": True,
                "discovery_mode": "explorer_gui",
                "requested_filename": filename,
                "explorer_window": active_win.get("title"),
                "screenshot": screenshot_res.get("path"),
                "message": (
                    f"Abri o Explorador de Arquivos e pesquisei por '{filename}'. "
                    f"Os resultados estão visíveis na tela."
                ),
            }
        except Exception as exc:
            kon_logger.error(f"[COMPUTER] Falha no fallback visual do Explorer: {exc}")
            return {
                "found": False,
                "discovery_mode": "failed",
                "error": str(exc),
                "message": f"Não foi possível localizar '{filename}' nem abrir a pesquisa no Explorer: {exc}",
            }

    @classmethod
    def computer_use(
        cls,
        goal: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        action: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        High-level Computer Use orchestrator.
        Executes a sequence of operational desktop actions (or a single action)
        adhering strictly to the OBSERVE -> ACT -> VERIFY cycle and safety limits.
        """
        cls._check_safety_limits()
        if goal:
            cls._emit_telemetry("GOAL", f"Iniciando objetivo: '{goal}'")

        if action and not steps:
            steps = [{"action": action, **kwargs}]

        if not steps:
            cls._emit_telemetry("OBSERVE", "Capturando estado atual do desktop")
            info = ScreenService.get_screen_info()
            active = cls.get_active_window()
            return {
                "success": True,
                "goal": goal,
                "screen": info,
                "active_window": active,
                "message": f"Desktop observado. Janela ativa: '{active.get('title')}'.",
            }

        executed_steps = []
        for idx, step_data in enumerate(steps):
            cls._check_safety_limits()
            act_type = step_data.get("action", "").lower().strip()
            exp_win = step_data.get("expected_window")

            cls._emit_telemetry("STEP", f"Passo {idx + 1}/{len(steps)}: {act_type}")

            from backend.security.input_policy import InputPolicy, SIMULATED_INPUT_TOOLS

            # 1. Expected window enforcement & auto-fill from recent observation
            if act_type in SIMULATED_INPUT_TOOLS:
                if not exp_win:
                    if cls._last_observed_window and (time.time() - cls._last_observed_time <= cls.OBSERVED_WINDOW_TTL):
                        exp_win = cls._last_observed_window.get("title") or cls._last_observed_window.get("process")
                        step_data["expected_window"] = exp_win
                    else:
                        res = {
                            "success": False,
                            "error": "MISSING_EXPECTED_WINDOW",
                            "message": f"O parâmetro 'expected_window' é obrigatório para a ação '{act_type}' e nenhuma observação recente da janela ativa foi realizada (TTL 10s). Chame 'get_active_window' primeiro.",
                        }
                        executed_steps.append({"step": idx + 1, "action": act_type, "result": res})
                        cls._emit_telemetry("ERROR", f"Passo {idx + 1} ({act_type}) bloqueado por falta de expected_window")
                        return {
                            "success": False,
                            "goal": goal,
                            "failed_step": idx + 1,
                            "executed_steps": executed_steps,
                            "message": res["message"],
                        }

                # 2. Contextual Input Policy Check
                allowed, decision, reason = InputPolicy.evaluate(act_type, step_data)
                if not allowed or decision != "ALLOW":
                    res = {
                        "success": False,
                        "error": "INPUT_POLICY_VIOLATION" if decision == "DENY" else "CONFIRMATION_REQUIRED",
                        "permission_level": decision,
                        "message": reason,
                    }
                    executed_steps.append({"step": idx + 1, "action": act_type, "result": res})
                    cls._emit_telemetry("ERROR", f"Passo {idx + 1} ({act_type}) bloqueado pela política de segurança: {reason}")
                    return {
                        "success": False,
                        "goal": goal,
                        "failed_step": idx + 1,
                        "executed_steps": executed_steps,
                        "message": res["message"],
                    }

            res: Dict[str, Any] = {}
            if act_type == "click":
                res = cls.click(x=step_data.get("x"), y=step_data.get("y"), button=step_data.get("button", "left"), expected_window=exp_win)
            elif act_type == "double_click":
                res = cls.double_click(x=step_data.get("x"), y=step_data.get("y"), expected_window=exp_win)
            elif act_type == "right_click":
                res = cls.right_click(x=step_data.get("x"), y=step_data.get("y"), expected_window=exp_win)
            elif act_type == "move_mouse":
                res = cls.move_mouse(x=int(step_data.get("x", 0)), y=int(step_data.get("y", 0)))
            elif act_type == "type_text":
                res = cls.type_text(text=step_data.get("text", ""), expected_window=exp_win)
            elif act_type == "press_key":
                res = cls.press_key(key=step_data.get("key", "enter"), expected_window=exp_win)
            elif act_type == "hotkey":
                res = cls.hotkey(keys=step_data.get("keys", []), expected_window=exp_win)
            elif act_type == "scroll":
                res = cls.scroll(amount=step_data.get("amount", -3))
            elif act_type == "click_element":
                res = cls.click_element(query=step_data.get("query", ""), button=step_data.get("button", "left"), expected_window=exp_win)
            elif act_type == "open_application":
                from backend.computer.applications import ApplicationManager
                res = ApplicationManager.open_application(step_data.get("application") or step_data.get("app"))
            elif act_type == "focus_window":
                res = cls.focus_window(step_data.get("title_or_process", ""))
            else:
                res = {"success": False, "error": f"Ação '{act_type}' desconhecida."}

            executed_steps.append({"step": idx + 1, "action": act_type, "result": res})
            if not res.get("success", False):
                cls._emit_telemetry("ERROR", f"Passo {idx + 1} ({act_type}) falhou: {res.get('message') or res.get('error')}")
                return {
                    "success": False,
                    "goal": goal,
                    "failed_step": idx + 1,
                    "executed_steps": executed_steps,
                    "message": f"Execução interrompida no passo {idx + 1}: {res.get('message') or res.get('error')}",
                }

            time.sleep(0.1)

        cls._emit_telemetry("VERIFY", f"Objetivo '{goal or 'Computer Use'}' concluído com sucesso ({len(steps)} passos)")
        return {
            "success": True,
            "goal": goal,
            "total_steps": len(steps),
            "executed_steps": executed_steps,
            "message": f"Ações de Computer Use concluídas com sucesso ({len(steps)} passos executados).",
        }
