"""
Windows-specific system utilities, folder resolution, and window state management for KON.
Provides native window inspection, focus switching, window state manipulation (minimize, maximize, restore, close),
and Explorer control.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
import os
import getpass
import platform
import time

import win32gui
import win32con
import win32process
import psutil

from backend.core.logger import kon_logger


class WindowsService:
    """
    Manages safe interaction with Windows OS, special directories, and GUI window states.
    """

    @staticmethod
    def is_windows() -> bool:
        return platform.system().lower() == "windows"

    @staticmethod
    def get_current_user() -> str:
        """
        Returns the logged in Windows username.
        """
        return os.getenv("USERNAME") or getpass.getuser()

    @classmethod
    def get_user_home(cls) -> Path:
        """
        Returns the user profile home directory (e.g., C:\\Users\\username).
        """
        user_profile = os.getenv("USERPROFILE")
        if user_profile:
            return Path(user_profile)
        return Path.home()

    @classmethod
    def get_desktop_dir(cls) -> Path:
        """
        Returns the real configured Desktop folder path.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "desktop" in kf and kf["desktop"].exists():
            return kf["desktop"]
        home = cls.get_user_home()
        onedrive_desktop = home / "OneDrive" / "Desktop"
        if onedrive_desktop.exists():
            return onedrive_desktop
        return home / "Desktop"

    @classmethod
    def get_downloads_dir(cls) -> Path:
        """
        Returns the real configured Downloads folder path.
        Discovered dynamically from Windows Shell API and Registry.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "downloads" in kf and kf["downloads"].exists():
            return kf["downloads"]
        return cls.get_user_home() / "Downloads"

    @classmethod
    def get_documents_dir(cls) -> Path:
        """
        Returns the real configured Documents folder path.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "documents" in kf and kf["documents"].exists():
            return kf["documents"]
        home = cls.get_user_home()
        onedrive_docs = home / "OneDrive" / "Documents"
        if onedrive_docs.exists():
            return onedrive_docs
        return home / "Documents"

    @classmethod
    def get_pictures_dir(cls) -> Path:
        """
        Returns the real configured Pictures folder path.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "pictures" in kf and kf["pictures"].exists():
            return kf["pictures"]
        home = cls.get_user_home()
        onedrive_pics = home / "OneDrive" / "Pictures"
        if onedrive_pics.exists():
            return onedrive_pics
        return home / "Pictures"

    @classmethod
    def get_videos_dir(cls) -> Path:
        """
        Returns the real configured Videos folder path.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "videos" in kf and kf["videos"].exists():
            return kf["videos"]
        return cls.get_user_home() / "Videos"

    @classmethod
    def get_music_dir(cls) -> Path:
        """
        Returns the real configured Music folder path.
        """
        from backend.computer.path_resolver import WindowsKnownFolders
        kf = WindowsKnownFolders.get_known_folders()
        if "music" in kf and kf["music"].exists():
            return kf["music"]
        return cls.get_user_home() / "Music"

    @classmethod
    def get_all_special_folders(cls) -> Dict[str, str]:
        """
        Returns all standard user directories mapped to their resolved string paths.
        """
        return {
            "user": cls.get_current_user(),
            "home": str(cls.get_user_home()),
            "desktop": str(cls.get_desktop_dir()),
            "downloads": str(cls.get_downloads_dir()),
            "documents": str(cls.get_documents_dir()),
            "pictures": str(cls.get_pictures_dir()),
            "videos": str(cls.get_videos_dir()),
            "music": str(cls.get_music_dir()),
        }

    @classmethod
    def resolve_folder_alias(cls, alias: str) -> Optional[Path]:
        """
        Maps natural language folder names to actual directory paths using WindowsKnownFolders
        and UniversalPathResolver.
        """
        from backend.computer.path_resolver import WindowsKnownFolders, PathAliasRegistry
        clean = alias.strip()
        # 1. Try known folders
        resolved = WindowsKnownFolders.resolve_known_folder(clean)
        if resolved and resolved.exists():
            return resolved

        # 2. Try alias registry
        alias_p = PathAliasRegistry.get_alias(clean)
        if alias_p and alias_p.exists():
            return alias_p

        return None

    # -------------------------------------------------------------
    # Window Inspection & State Management
    # -------------------------------------------------------------

    @classmethod
    def list_windows(cls, query: Optional[str] = None) -> Dict[str, Any]:
        """
        Lists all visible top-level windows currently open on the desktop.
        """
        windows: List[Dict[str, Any]] = []

        def enum_handler(hwnd: int, extra: Any) -> bool:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if title:
                    if title in ("Program Manager", "Default IME", "MSCTFIME UI"):
                        return True

                    rect = win32gui.GetWindowRect(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]

                    if width > 50 and height > 50:
                        proc_name = ""
                        try:
                            _, pid = win32process.GetWindowThreadProcessId(hwnd)
                            if pid:
                                proc_name = psutil.Process(pid).name()
                        except Exception:
                            pass

                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                            "process": proc_name,
                            "bounds": {"x": rect[0], "y": rect[1], "width": width, "height": height},
                        })
            return True

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception as e:
            kon_logger.debug(f"[WINDOWS] Erro no EnumWindows: {e}")

        if query:
            clean_query = query.strip().lower()
            windows = [
                w for w in windows
                if clean_query in w["title"].lower() or clean_query in w["process"].lower()
            ]

        return {
            "success": True,
            "count": len(windows),
            "windows": windows,
            "message": f"Encontradas {len(windows)} janelas visíveis.",
        }

    @classmethod
    def get_active_window(cls) -> Dict[str, Any]:
        """
        Returns information about the currently focused top-level window.
        """
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            all_w = cls.list_windows()
            if all_w.get("windows"):
                top_w = all_w["windows"][0]
                return {
                    "success": True,
                    "hwnd": top_w["hwnd"],
                    "title": top_w["title"],
                    "process": top_w["process"],
                    "bounds": top_w["bounds"],
                    "message": f"Janela ativa: '{top_w['title']}' ({top_w['process']})",
                }
            return {
                "success": True,
                "hwnd": 0,
                "title": "Área de Trabalho (Desktop)",
                "process": "explorer.exe",
                "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                "message": "Área de trabalho ativa.",
            }

        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        bounds = {
            "x": rect[0],
            "y": rect[1],
            "width": max(0, rect[2] - rect[0]),
            "height": max(0, rect[3] - rect[1]),
        }

        proc_name = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                proc_name = psutil.Process(pid).name()
        except Exception:
            pass

        return {
            "success": True,
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "bounds": bounds,
            "message": f"Janela ativa: '{title}' ({proc_name})",
        }

    @classmethod
    def find_window_hwnd(cls, title_or_process: str) -> Optional[int]:
        """
        Finds the HWND of a window matching title or process name.
        """
        res = cls.list_windows(query=title_or_process)
        matches = res.get("windows", [])
        if matches:
            return matches[0]["hwnd"]
        return None

    @classmethod
    def focus_window(cls, title_or_process: str) -> Dict[str, Any]:
        """
        Brings a window matching title or process name to the foreground.
        """
        hwnd = cls.find_window_hwnd(title_or_process)
        if not hwnd:
            return {
                "success": False,
                "error": "WINDOW_NOT_FOUND",
                "message": f"Janela '{title_or_process}' não foi encontrada.",
            }

        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            title = win32gui.GetWindowText(hwnd)
            kon_logger.info(f"[COMPUTER] Focus window: '{title}' (hwnd={hwnd})")
            return {
                "success": True,
                "hwnd": hwnd,
                "title": title,
                "message": f"Janela '{title}' colocada em primeiro plano.",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "message": f"Não foi possível focar a janela: {exc}",
            }

    @classmethod
    def _resolve_target_hwnd(cls, title_or_process: Optional[str] = None) -> Optional[int]:
        """Resolves target window HWND with fallback to active or topmost visible window."""
        if title_or_process:
            return cls.find_window_hwnd(title_or_process)
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            return hwnd
        active = cls.get_active_window()
        if active.get("hwnd"):
            return active["hwnd"]
        all_w = cls.list_windows()
        if all_w.get("windows"):
            return all_w["windows"][0]["hwnd"]
        return None

    @classmethod
    def maximize_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        """
        Maximizes the targeted window (or the currently active window if omitted).
        """
        hwnd = cls._resolve_target_hwnd(title_or_process)
        if not hwnd:
            return {"success": False, "error": "WINDOW_NOT_FOUND", "message": "Nenhuma janela encontrada para maximizar."}

        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        title = win32gui.GetWindowText(hwnd)
        kon_logger.info(f"[COMPUTER] Maximize window: '{title}'")
        return {"success": True, "hwnd": hwnd, "title": title, "message": f"Janela '{title}' maximizada."}

    @classmethod
    def minimize_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        """
        Minimizes the targeted window (or the currently active window if omitted).
        """
        hwnd = cls._resolve_target_hwnd(title_or_process)
        if not hwnd:
            return {"success": False, "error": "WINDOW_NOT_FOUND", "message": "Nenhuma janela encontrada para minimizar."}

        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        title = win32gui.GetWindowText(hwnd)
        kon_logger.info(f"[COMPUTER] Minimize window: '{title}'")
        return {"success": True, "hwnd": hwnd, "title": title, "message": f"Janela '{title}' minimizada."}

    @classmethod
    def restore_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        """
        Restores the targeted window to normal state.
        """
        hwnd = cls._resolve_target_hwnd(title_or_process)
        if not hwnd:
            return {"success": False, "error": "WINDOW_NOT_FOUND", "message": "Nenhuma janela encontrada para restaurar."}

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        title = win32gui.GetWindowText(hwnd)
        kon_logger.info(f"[COMPUTER] Restore window: '{title}'")
        return {"success": True, "hwnd": hwnd, "title": title, "message": f"Janela '{title}' restaurada."}

    @classmethod
    def close_window(cls, title_or_process: Optional[str] = None) -> Dict[str, Any]:
        """
        Closes the targeted window (or the currently active window if omitted).
        """
        hwnd = cls._resolve_target_hwnd(title_or_process)
        if not hwnd:
            return {"success": False, "error": "WINDOW_NOT_FOUND", "message": "Nenhuma janela encontrada para fechar."}

        title = win32gui.GetWindowText(hwnd)
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        kon_logger.info(f"[COMPUTER] Close window: '{title}'")
        return {"success": True, "hwnd": hwnd, "title": title, "message": f"Janela '{title}' fechada."}
