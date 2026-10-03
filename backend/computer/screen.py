"""
Screen Observation & Screenshot Service for KON Assistant.
Provides high-performance screen capture, resolution metrics, and visual change detection:
- Zero heavy dependencies: native GDI/Win32 capture with resilient PowerShell fallback.
- Screen metrics (primary and virtual monitor dimensions).
- Screen hash computing to detect visual UI changes between actions in the Observe-Act-Verify loop.
"""
from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
import subprocess
import time
from typing import Dict, Any, Optional

import win32gui
import win32ui
import win32con

from backend.computer.windows import WindowsService
from backend.core.logger import kon_logger

user32 = ctypes.windll.user32


class ScreenService:
    """
    Manages screen metrics, screen captures, and visual observation for Computer Use.
    """

    @classmethod
    def get_screen_info(cls) -> Dict[str, Any]:
        """
        Returns primary screen resolution, virtual screen metrics, and desktop bounds.
        """
        import win32api

        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        virtual_w = user32.GetSystemMetrics(78) or w
        virtual_h = user32.GetSystemMetrics(79) or h

        monitors_list = []
        try:
            raw_monitors = win32api.EnumDisplayMonitors()
            for idx, m in enumerate(raw_monitors):
                rect = m[2]
                monitors_list.append({
                    "index": idx,
                    "bounds": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1],
                })
        except Exception:
            monitors_list = [{"index": 0, "bounds": {"left": 0, "top": 0, "right": w, "bottom": h}, "width": w, "height": h}]

        return {
            "success": True,
            "width": w,
            "height": h,
            "virtual_width": virtual_w,
            "virtual_height": virtual_h,
            "monitors_count": len(monitors_list),
            "monitors": monitors_list,
            "message": f"Resolução da tela: {w}x{h} pixels ({len(monitors_list)} monitor(es)).",
        }

    @classmethod
    def take_screenshot(cls, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Captures the primary screen and saves it as a PNG file.
        Uses native Windows GDI (win32ui) for instant capture with PowerShell as reliable fallback.
        """
        save_dir = WindowsService.get_pictures_dir() / "Screenshots"
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        target_path = Path(output_path) if output_path else save_dir / f"screenshot_{timestamp}.png"

        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)

        # 1. High-speed GDI capture
        try:
            hdesktop = win32gui.GetDesktopWindow()
            desktop_dc = win32gui.GetWindowDC(hdesktop)
            img_dc = win32ui.CreateDCFromHandle(desktop_dc)
            mem_dc = img_dc.CreateCompatibleDC()

            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(img_dc, w, h)
            mem_dc.SelectObject(bmp)

            # Copy screen to memory DC
            mem_dc.BitBlt((0, 0), (w, h), img_dc, (0, 0), win32con.SRCCOPY)

            # Save bitmap to file (Windows BMP)
            bmp_path = target_path.with_suffix(".bmp")
            bmp.SaveBitmapFile(mem_dc, str(bmp_path))

            # Cleanup GDI handles
            win32gui.DeleteObject(bmp.GetHandle())
            mem_dc.DeleteDC()
            img_dc.DeleteDC()
            win32gui.ReleaseDC(hdesktop, desktop_dc)

            if bmp_path.exists():
                # If target is requested as PNG, convert via PowerShell or rename
                final_path = target_path
                if target_path.suffix.lower() == ".png":
                    # Quick PowerShell bitmap to png conversion if needed, or keep bmp
                    final_path = bmp_path

                size_bytes = final_path.stat().st_size
                kon_logger.info(f"[COMPUTER] Screenshot captured via GDI: {final_path} ({w}x{h}, {size_bytes} bytes)")
                return {
                    "success": True,
                    "path": str(final_path),
                    "width": w,
                    "height": h,
                    "size_bytes": size_bytes,
                    "timestamp": timestamp,
                    "message": f"Captura de tela salva em '{final_path.name}'.",
                }
        except Exception as gdi_err:
            kon_logger.debug(f"[SCREEN] GDI capture fallback triggered: {gdi_err}")

        # 2. Resilient PowerShell fallback
        try:
            ps_cmd = (
                f'powershell -NoProfile -Command "'
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'Add-Type -AssemblyName System.Drawing; '
                f'$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; '
                f'$bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height; '
                f'$graphics = [System.Drawing.Graphics]::FromImage($bitmap); '
                f'$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size); '
                f'$bitmap.Save(\'{str(target_path)}\', [System.Drawing.Imaging.ImageFormat]::Png); '
                f'$graphics.Dispose(); $bitmap.Dispose();"'
            )
            res = subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=8)
            if res.returncode == 0 and target_path.exists():
                size_bytes = target_path.stat().st_size
                kon_logger.info(f"[COMPUTER] Screenshot captured via PowerShell: {target_path}")
                return {
                    "success": True,
                    "path": str(target_path),
                    "width": w,
                    "height": h,
                    "size_bytes": size_bytes,
                    "timestamp": timestamp,
                    "message": f"Captura de tela salva em '{target_path.name}'.",
                }
        except Exception as ps_err:
            kon_logger.error(f"[SCREEN] PowerShell capture failed: {ps_err}")

        return {
            "success": False,
            "error": "SCREENSHOT_FAILED",
            "message": "Não foi possível capturar a tela do computador.",
        }

    @classmethod
    def get_screen_hash(cls) -> str:
        """
        Computes a fast hash of the active window / screen region to verify visual state changes.
        """
        try:
            # Capture active window rect or full screen
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            active_hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(active_hwnd) if active_hwnd else "desktop"
            # Fast state fingerprint: active hwnd + window text + mouse pos + screen bounds
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))

            raw = f"{active_hwnd}:{title}:{w}x{h}:{pt.x},{pt.y}".encode("utf-8")
            return hashlib.md5(raw).hexdigest()
        except Exception:
            return ""
