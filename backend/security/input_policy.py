"""
Input Policy Module for KON Security Layer.
Enforces strict contextual policies on simulated user input (mouse, keyboard):
- Blocks all simulated input when foreground window is the KON HUD.
- Blocks simulated typing and hotkeys when foreground window is a terminal/shell or Run dialog.
- Requires user confirmation (CONFIRM) for destructive Explorer actions (Delete, Shift+Delete, drag).
- Requires user confirmation (CONFIRM) for sensitive system hotkeys (Win+R, Win+X, Ctrl+Shift+Esc, Alt+F4, Ctrl+Alt+Delete, Win+L).
"""
from __future__ import annotations

import re
from typing import Dict, Any, Optional, Tuple, List, Set
from backend.core.logger import kon_logger

# Shell & terminal process executables
SHELL_PROCESSES: Set[str] = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "conhost.exe",
    "wt.exe",
    "bash.exe",
    "wsl.exe",
}

# Sensitive hotkey combos that bypass controls or terminate tasks
SENSITIVE_HOTKEYS = (
    {"win", "r"},
    {"windows", "r"},
    {"win", "x"},
    {"windows", "x"},
    {"ctrl", "shift", "esc"},
    {"ctrl", "shift", "escape"},
    {"control", "shift", "esc"},
    {"control", "shift", "escape"},
    {"alt", "f4"},
    {"ctrl", "alt", "delete"},
    {"ctrl", "alt", "del"},
    {"control", "alt", "delete"},
    {"control", "alt", "del"},
    {"win", "l"},
    {"windows", "l"},
)

SIMULATED_INPUT_TOOLS: Set[str] = {
    "click",
    "double_click",
    "right_click",
    "drag",
    "type_text",
    "press_key",
    "hotkey",
    "mouse_down",
    "mouse_up",
}


def _extract_keys(args: Dict[str, Any]) -> List[str]:
    """Normalizes key or keys from arguments into a lowercase list."""
    keys: List[str] = []
    if "key" in args and args["key"]:
        keys.append(str(args["key"]).strip().lower())
    elif "keys" in args and args["keys"]:
        raw_keys = args["keys"]
        if isinstance(raw_keys, str):
            parts = [k.strip().lower() for k in re.split(r"[+\-\s]+", raw_keys) if k.strip()]
            keys.extend(parts)
        elif isinstance(raw_keys, (list, tuple)):
            for k in raw_keys:
                clean = str(k).strip().lower()
                if clean:
                    keys.append(clean)
    return keys


def _is_sensitive_hotkey(keys: List[str]) -> bool:
    """Checks whether the keys match any recognized sensitive system hotkey."""
    key_set = set(keys)
    for sensitive_set in SENSITIVE_HOTKEYS:
        if sensitive_set.issubset(key_set):
            return True
    return False


class InputPolicy:
    """
    Evaluates contextual risk of simulated input actions before execution.
    """

    @classmethod
    def evaluate(
        cls,
        tool_name: str,
        args: Dict[str, Any],
        active_window: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, str]:
        """
        Evaluates the requested simulated input tool against security policies.
        Returns:
            (allowed: bool, decision: "ALLOW" | "CONFIRM" | "DENY", reason: str)
        """
        if tool_name not in SIMULATED_INPUT_TOOLS:
            return True, "ALLOW", "Ferramenta não é de entrada simulada."

        if active_window is None:
            from backend.computer.windows import WindowsService
            active_window = WindowsService.get_active_window()

        title = (active_window.get("title") or "").strip().lower()
        proc = (active_window.get("process") or "").strip().lower()

        # -----------------------------------------------------------------
        # 1. KON HUD Window: Refuse ALL simulated input (Anti-Self-Authorization)
        # -----------------------------------------------------------------
        is_hud = (
            "kon hud" in title
            or "kon assistant" in title
            or ("5173" in title)
            or (proc == "chrome.exe" and "5173" in title)
            or (title == "kon" and proc != "explorer.exe")
        )
        if is_hud:
            msg = "Toda entrada simulada é bloqueada na janela do HUD do KON para evitar auto-autorização."
            kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Bloqueio HUD: {tool_name} em '{title}' ({proc}).")
            return False, "DENY", msg

        # -----------------------------------------------------------------
        # 2. Terminal / Shell / Run Dialog: Refuse type_text & hotkey
        # -----------------------------------------------------------------
        is_shell = (
            proc in SHELL_PROCESSES
            or (proc == "explorer.exe" and (title == "executar" or title == "run" or "executar" in title))
        )
        if is_shell and tool_name in ("type_text", "hotkey", "press_key"):
            msg = f"Entrada simulada de texto/teclado ({tool_name}) bloqueada em terminal/shell ({proc or title}) por política de segurança."
            kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Bloqueio Shell: {tool_name} em '{title}' ({proc}).")
            return False, "DENY", msg

        # -----------------------------------------------------------------
        # 3. Sensitive Hotkeys: Always require CONFIRM
        # -----------------------------------------------------------------
        if tool_name in ("hotkey", "press_key"):
            keys = _extract_keys(args)
            if _is_sensitive_hotkey(keys):
                hotkey_str = "+".join(keys)
                msg = f"Atalho sensível do sistema '{hotkey_str}' requer confirmação explícita do usuário."
                kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Confirmação necessária para atalho sensível: {hotkey_str}")
                return False, "CONFIRM", msg

        # -----------------------------------------------------------------
        # 4. Windows Explorer (explorer.exe): Delete / Shift+Delete & Drag require CONFIRM
        # -----------------------------------------------------------------
        if proc == "explorer.exe":
            if tool_name == "drag":
                msg = "Ação de arrasto no Explorador de Arquivos requer confirmação explícita do usuário."
                kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Confirmação necessária para drag no Explorer.")
                return False, "CONFIRM", msg

            if tool_name in ("press_key", "hotkey"):
                keys = _extract_keys(args)
                if any(k in ("delete", "del") for k in keys):
                    msg = "Exclusão via teclado no Explorador de Arquivos requer confirmação explícita do usuário."
                    kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Confirmação necessária para Delete no Explorer.")
                    return False, "CONFIRM", msg

        # -----------------------------------------------------------------
        # 5. KON Browser Session (Phase 2 extension hook)
        # -----------------------------------------------------------------
        is_kon_browser = (
            "kon - browser" in title
            or "kon_browser" in title
            or active_window.get("is_kon_browser", False)
        )
        if is_kon_browser and tool_name in ("click", "double_click", "right_click", "drag", "type_text", "hotkey", "press_key"):
            msg = "Interação com o navegador do KON deve ser feita via ferramentas 'browser_*', não por mouse/teclado simulado."
            kon_logger.warning(f"[SECURITY] [INPUT_POLICY] Entrada simulada bloqueada no navegador KON.")
            return False, "DENY", msg

        return True, "ALLOW", "Ação de entrada simulada permitida pelo contexto."
