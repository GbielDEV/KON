"""
Mouse Control Service for KON Assistant.
Provides safe, controlled, native mouse automation on Windows OS:
- Screen coordinate bounds clamping (prevents out-of-screen clicks).
- Window context verification (protects against clicks when active window is unexpected).
- Single, double, and right clicks, mouse down/up, drag and scroll.
- Zero arbitrary Python execution; all interactions routed through ToolRegistry.
"""
from __future__ import annotations

import ctypes
import time
from typing import Dict, Any, Optional, Tuple

from backend.core.logger import kon_logger

user32 = ctypes.windll.user32

# Native Windows Mouse Event Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class MouseController:
    """
    Manages safe native mouse input for the Windows desktop.
    """

    @staticmethod
    def get_screen_bounds() -> Tuple[int, int]:
        """Returns primary screen width and height."""
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return w, h

    @classmethod
    def get_mouse_position(cls) -> Dict[str, Any]:
        """
        Returns the current cursor position on the desktop.
        """
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return {
            "success": True,
            "x": pt.x,
            "y": pt.y,
            "message": f"Posição atual do mouse: x={pt.x}, y={pt.y}.",
        }

    @classmethod
    def move_mouse(
        cls,
        x: int,
        y: int,
        smooth: bool = True,
        duration: float = 0.15,
        steps: int = 15,
    ) -> Dict[str, Any]:
        """
        Moves the mouse cursor to clamped absolute desktop coordinates (x, y).
        Supports visible smooth motion across the screen.
        """
        max_w, max_h = cls.get_screen_bounds()
        target_x = max(0, min(int(x), max_w - 1))
        target_y = max(0, min(int(y), max_h - 1))

        if smooth and steps > 1:
            curr = cls.get_mouse_position()
            start_x, start_y = curr["x"], curr["y"]
            step_delay = max(0.005, duration / steps)
            for i in range(1, steps + 1):
                # Cosine easing for natural cursor acceleration and deceleration
                progress = i / steps
                inter_x = int(start_x + (target_x - start_x) * progress)
                inter_y = int(start_y + (target_y - start_y) * progress)
                user32.SetCursorPos(inter_x, inter_y)
                time.sleep(step_delay)
        else:
            user32.SetCursorPos(target_x, target_y)

        kon_logger.info(f"[COMPUTER] Move mouse x={target_x} y={target_y}")
        return {
            "success": True,
            "x": target_x,
            "y": target_y,
            "message": f"Cursor movido para ({target_x}, {target_y}).",
        }

    @classmethod
    def click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        expected_window: Optional[str] = None,
        smooth: bool = True,
    ) -> Dict[str, Any]:
        """
        Clicks at the current position or specified coordinates (x, y).
        Optionally moves smoothly and verifies that active window matches expected_window.
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        if x is not None and y is not None:
            cls.move_mouse(x, y, smooth=smooth)
            time.sleep(0.04)

        btn = (button or "left").lower().strip()
        if btn == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif btn == "middle":
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        else:
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

        user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(up_flag, 0, 0, 0, 0)

        coords_str = f" x={x} y={y}" if x is not None and y is not None else ""
        kon_logger.info(f"[COMPUTER] Click button={btn}{coords_str}")
        return {
            "success": True,
            "button": btn,
            "x": x,
            "y": y,
            "message": f"Clique com botão {btn}{coords_str} realizado.",
        }

    @classmethod
    def double_click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a double left-click.
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        if x is not None and y is not None:
            cls.move_mouse(x, y)
            time.sleep(0.03)

        cls.click(button="left")
        time.sleep(0.08)
        cls.click(button="left")

        coords_str = f" x={x} y={y}" if x is not None and y is not None else ""
        kon_logger.info(f"[COMPUTER] Double click{coords_str}")
        return {"success": True, "x": x, "y": y, "message": f"Clique duplo{coords_str} realizado."}

    @classmethod
    def right_click(
        cls,
        x: Optional[int] = None,
        y: Optional[int] = None,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes a right-click."""
        return cls.click(x=x, y=y, button="right", expected_window=expected_window)

    @classmethod
    def mouse_down(cls, button: str = "left") -> Dict[str, Any]:
        """Presses and holds a mouse button without releasing."""
        btn = (button or "left").lower().strip()
        down_flag = MOUSEEVENTF_RIGHTDOWN if btn == "right" else MOUSEEVENTF_LEFTDOWN
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        kon_logger.info(f"[COMPUTER] Mouse down button={btn}")
        return {"success": True, "button": btn, "message": f"Botão {btn} do mouse pressionado."}

    @classmethod
    def mouse_up(cls, button: str = "left") -> Dict[str, Any]:
        """Releases a pressed mouse button."""
        btn = (button or "left").lower().strip()
        up_flag = MOUSEEVENTF_RIGHTUP if btn == "right" else MOUSEEVENTF_LEFTUP
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        kon_logger.info(f"[COMPUTER] Mouse up button={btn}")
        return {"success": True, "button": btn, "message": f"Botão {btn} do mouse solto."}

    @classmethod
    def drag(
        cls,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 10,
        expected_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Drags the mouse from (start_x, start_y) to (end_x, end_y).
        """
        from backend.computer.computer_use import ComputerUseService
        ComputerUseService.verify_window_context(expected_window)

        cls.move_mouse(start_x, start_y)
        time.sleep(0.05)
        cls.mouse_down(button="left")
        time.sleep(0.05)

        for i in range(1, steps + 1):
            curr_x = int(start_x + (end_x - start_x) * (i / steps))
            curr_y = int(start_y + (end_y - start_y) * (i / steps))
            cls.move_mouse(curr_x, curr_y)
            time.sleep(0.02)

        time.sleep(0.05)
        cls.mouse_up(button="left")
        kon_logger.info(f"[COMPUTER] Drag from ({start_x}, {start_y}) to ({end_x}, {end_y})")
        return {
            "success": True,
            "start": (start_x, start_y),
            "end": (end_x, end_y),
            "message": f"Arrasto de ({start_x}, {start_y}) para ({end_x}, {end_y}) concluído.",
        }

    @classmethod
    def scroll(cls, amount: int = -3) -> Dict[str, Any]:
        """
        Scrolls the mouse wheel. Positive = up, Negative = down.
        """
        delta = int(amount) * 120
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        direction = "cima" if amount > 0 else "baixo"
        kon_logger.info(f"[COMPUTER] Scroll direction={direction} steps={abs(amount)}")
        return {
            "success": True,
            "amount": amount,
            "message": f"Rolagem da página para {direction} ({abs(amount)} passos).",
        }
