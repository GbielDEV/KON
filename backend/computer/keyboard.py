"""
Keyboard Control Service for KON Assistant.
Provides safe, controlled, native keyboard automation on Windows OS:
- Direct Unicode character injection preserving Brazilian Portuguese accents (ç, ã, é, ó, etc.).
- Extended virtual key support (Enter, Esc, Tab, Win, Ctrl, Alt, Shift, Arrows, F1-F12).
- Composite hotkey shortcuts (Ctrl+C, Ctrl+V, Alt+Tab, Win+R, etc.).
- Active window context verification to prevent typing in unintended applications.
- Zero arbitrary shell or script execution.
"""
from __future__ import annotations

import ctypes
import time
from typing import Dict, Any, Optional
import win32con

from backend.core.logger import kon_logger

user32 = ctypes.windll.user32

# Native Keyboard Flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# Windows Virtual Key Code mappings
VK_MAPPINGS = {
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
    "backspace": win32con.VK_BACK,
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    "delete": win32con.VK_DELETE,
    "del": win32con.VK_DELETE,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "ctrl": win32con.VK_CONTROL,
    "control": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
    "win": win32con.VK_LWIN,
    "windows": win32con.VK_LWIN,
    "f1": win32con.VK_F1,
    "f2": win32con.VK_F2,
    "f3": win32con.VK_F3,
    "f4": win32con.VK_F4,
    "f5": win32con.VK_F5,
    "f6": win32con.VK_F6,
    "f7": win32con.VK_F7,
    "f8": win32con.VK_F8,
    "f9": win32con.VK_F9,
    "f10": win32con.VK_F10,
    "f11": win32con.VK_F11,
    "f12": win32con.VK_F12,
    "insert": win32con.VK_INSERT,
    "printscreen": win32con.VK_SNAPSHOT,
    "prtscr": win32con.VK_SNAPSHOT,
    "capslock": win32con.VK_CAPITAL,
    "numlock": win32con.VK_NUMLOCK,
}


class KeyboardController:
    """
    Manages safe native keyboard input for the Windows desktop.
    """

    @classmethod
    def type_text(cls, text: str, expected_window: Optional[str] = None) -> Dict[str, Any]:
        """
        Types text natively using Windows Unicode key events.
        Preserves PT-BR characters and accents (ç, ã, é, ó, etc.).
        Guarded by expected_window verification.
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        for char in text:
            code = ord(char)
            # Key down
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            time.sleep(0.01)
            # Key up
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

        kon_logger.info(f"[COMPUTER] Type text length={len(text)}")
        return {
            "success": True,
            "typed_length": len(text),
            "message": f"Texto digitado ({len(text)} caracteres).",
        }

    @classmethod
    def press_key(cls, key: str, expected_window: Optional[str] = None) -> Dict[str, Any]:
        """
        Presses and releases a single special key (e.g. enter, tab, escape, backspace).
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        clean_key = key.strip().lower()
        vk_code = VK_MAPPINGS.get(clean_key)
        if not vk_code:
            if len(clean_key) == 1:
                return cls.type_text(clean_key, expected_window=expected_window)
            return {"success": False, "error": "UNKNOWN_KEY", "message": f"Tecla desconhecida: '{key}'"}

        user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)

        kon_logger.info(f"[COMPUTER] Press key '{clean_key}'")
        return {"success": True, "key": clean_key, "message": f"Tecla '{clean_key}' pressionada."}

    @classmethod
    def hotkey(cls, keys: Any, expected_window: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes a composite key combination (e.g. ['ctrl', 'c'], ['alt', 'tab'], or 'ctrl+l').
        Presses keys in order, then releases in reverse order.
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        if isinstance(keys, str):
            import re
            key_list = [k.strip() for k in re.split(r"[+\-\s]+", keys) if k.strip()]
        elif isinstance(keys, (list, tuple)):
            key_list = list(keys)
        else:
            return {"success": False, "error": "INVALID_FORMAT", "message": "As teclas devem ser uma lista ou texto (ex: 'ctrl+c')."}

        vk_codes = []
        for k in key_list:
            clean = str(k).strip().lower()
            vk = VK_MAPPINGS.get(clean)
            if not vk and len(clean) == 1:
                vk = user32.VkKeyScanW(ord(clean)) & 0xFF
            if vk:
                vk_codes.append(vk)

        if not vk_codes:
            return {"success": False, "error": "INVALID_KEYS", "message": f"Combinação de teclas inválida: {keys}"}

        # Press keys in sequence
        for vk in vk_codes:
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)

        time.sleep(0.05)

        # Release keys in reverse sequence
        for vk in reversed(vk_codes):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)

        keys_str = "+".join(keys)
        kon_logger.info(f"[COMPUTER] Hotkey '{keys_str}'")
        return {"success": True, "combination": keys, "message": f"Atalho '{keys_str}' executado."}
