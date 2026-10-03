"""
Application launcher and management service for Windows.
Safe process launching with Windows Registry resolution and NO arbitrary shell execution.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import subprocess
import os
import winreg
import time

from backend.core.logger import kon_logger
from backend.security.subprocess_sandbox import build_safe_env


class ApplicationManager:
    """
    Manages safe execution of authorized Windows applications.
    Never executes arbitrary strings in shell.
    """

    # Whitelist of recognized SAFE application identifiers
    ALLOWED_APPLICATIONS = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "notepad": "notepad.exe",
        "bloco de notas": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "calculadora": "calc.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "explorer": "explorer.exe",
        "explorador": "explorer.exe",
        "spotify": "Spotify.exe",
        "code": "Code.exe",
        "vscode": "Code.exe",
        "visual studio code": "Code.exe",
        "vs code": "Code.exe",
        "paint": "mspaint.exe",
        "mspaint": "mspaint.exe",
        "discord": "Discord.exe",
        "steam": "steam.exe",
        "slack": "slack.exe",
        "vlc": "vlc.exe",
        "word": "WINWORD.EXE",
        "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE",
    }

    # Terminals, shells, and administrative utilities requiring explicit CONFIRM
    RESTRICTED_APPLICATIONS = {
        "terminal": "wt.exe",
        "cmd": "cmd.exe",
        "prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "pwsh": "pwsh.exe",
        "wt": "wt.exe",
        "regedit": "regedit.exe",
        "mmc": "mmc.exe",
        "bash": "bash.exe",
        "wsl": "wsl.exe",
    }

    RESTRICTED_BINARIES = frozenset({
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "wt.exe",
        "windowsterminal.exe",
        "regedit.exe",
        "mmc.exe",
        "bash.exe",
        "wsl.exe",
        "conhost.exe",
    })

    @classmethod
    def resolve_application_path(cls, app_key: str) -> Optional[Path]:
        """
        Locates the real executable on Windows using the Windows Registry
        and standard program file locations. Never accepts raw executable paths from user.
        """
        target_binary = cls.ALLOWED_APPLICATIONS.get(app_key.lower().strip())
        if not target_binary:
            target_binary = cls.RESTRICTED_APPLICATIONS.get(app_key.lower().strip())
        if not target_binary:
            # Fallback: check if app_key with .exe is a known safe or restricted binary
            clean_name = f"{app_key.lower().strip()}.exe"
            if clean_name in cls.ALLOWED_APPLICATIONS.values() or clean_name in cls.RESTRICTED_BINARIES:
                target_binary = clean_name
            else:
                return None

        # 1. Query Windows Registry: App Paths
        registry_keys = [
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{target_binary}"),
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{target_binary}"),
        ]

        for root, subkey in registry_keys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        exe_path = Path(val.strip('"'))
                        if exe_path.exists() and exe_path.is_file():
                            return exe_path
            except (OSError, FileNotFoundError):
                pass

        # 2. Check shutil.which
        import shutil
        which_path = shutil.which(target_binary)
        if which_path:
            p = Path(which_path)
            if p.exists() and p.is_file():
                return p

        # 3. Check Standard Windows Program Directories
        program_roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
            os.environ.get("APPDATA", r"C:\Users\Default\AppData\Roaming"),
            r"C:\Windows\System32",
            r"C:\Windows",
        ]

        known_subpaths = {
            "chrome.exe": [
                r"Google\Chrome\Application\chrome.exe",
            ],
            "notepad.exe": [
                r"notepad.exe",
                r"..\Windows\notepad.exe",
                r"..\Windows\System32\notepad.exe",
            ],
            "calc.exe": [
                r"calc.exe",
                r"..\Windows\System32\calc.exe",
            ],
            "msedge.exe": [
                r"Microsoft\Edge\Application\msedge.exe",
            ],
            "Spotify.exe": [
                r"Spotify\Spotify.exe",
            ],
            "Code.exe": [
                r"Programs\Microsoft VS Code\Code.exe",
            ],
        }

        subpaths = known_subpaths.get(target_binary, [target_binary])
        for root_dir in program_roots:
            if not root_dir:
                continue
            for rel_path in subpaths:
                candidate = (Path(root_dir) / rel_path).resolve()
                if candidate.exists() and candidate.is_file():
                    return candidate

        # 4. Fallback: Search in dynamically discovered installed applications
        discovered = cls.discover_installed_applications()
        if app_key.lower().strip() in discovered:
            return discovered[app_key.lower().strip()]
        for name, p in discovered.items():
            if app_key.lower().strip() in name or name in app_key.lower().strip():
                return p

        return None

    # Cached installed applications
    _INSTALLED_APPS_CACHE: Dict[str, Path] = {}
    _LAST_SCAN_TIME: float = 0.0

    @classmethod
    def discover_installed_applications(cls, force_rescan: bool = False) -> Dict[str, Path]:
        """
        Discovers installed applications on the Windows system by querying the Start Menu
        and Windows Registry App Paths. Caches results to ensure near-zero latency.
        Strictly excludes terminals, shells, and administrative binaries from safe discovery.
        """
        now = time.time()
        if not force_rescan and cls._INSTALLED_APPS_CACHE and (now - cls._LAST_SCAN_TIME < 300):
            return dict(cls._INSTALLED_APPS_CACHE)

        discovered: Dict[str, Path] = {}

        # 1. Windows Registry: App Paths
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as app_paths:
                    num_subkeys, _, _ = winreg.QueryInfoKey(app_paths)
                    for i in range(num_subkeys):
                        try:
                            subkey_name = winreg.EnumKey(app_paths, i)
                            with winreg.OpenKey(app_paths, subkey_name) as item_key:
                                val, _ = winreg.QueryValueEx(item_key, "")
                                if val:
                                    p = Path(val.strip('"'))
                                    if p.exists() and p.is_file() and p.suffix.lower() == ".exe":
                                        if p.name.lower() in cls.RESTRICTED_BINARIES:
                                            continue
                                        clean_key = subkey_name.lower().replace(".exe", "").strip()
                                        discovered[clean_key] = p
                        except Exception:
                            continue
            except Exception:
                pass

        # 2. Start Menu shortcuts (.lnk)
        start_menu_dirs = [
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        ]

        wscript = None
        try:
            import win32com.client
            wscript = win32com.client.Dispatch("WScript.Shell")
        except Exception:
            pass

        if wscript:
            for sm_dir in start_menu_dirs:
                if not os.path.exists(sm_dir):
                    continue
                try:
                    for root_dir, _, files in os.walk(sm_dir):
                        for f in files:
                            if f.lower().endswith(".lnk"):
                                lnk_path = os.path.join(root_dir, f)
                                try:
                                    shortcut = wscript.CreateShortcut(lnk_path)
                                    target = shortcut.TargetPath
                                    if target and target.lower().endswith(".exe") and os.path.isfile(target):
                                        if Path(target).name.lower() in cls.RESTRICTED_BINARIES:
                                            continue
                                        app_name = f.lower()[:-4].strip()
                                        clean_name = "".join(c for c in app_name if c.isalnum() or c in (" ", "-", "_")).strip()
                                        if clean_name and clean_name not in discovered:
                                            discovered[clean_name] = Path(target)
                                except Exception:
                                    continue
                except Exception:
                    pass

        cls._INSTALLED_APPS_CACHE = discovered
        cls._LAST_SCAN_TIME = now
        kon_logger.debug(f"[APPS] Descobertos {len(discovered)} aplicativos instalados no Windows.")
        return dict(cls._INSTALLED_APPS_CACHE)

    @classmethod
    def list_installed_applications(cls, query: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns a list of all recognized and installed applications on Windows.
        """
        apps = cls.discover_installed_applications()
        result_list = []
        for name, p in apps.items():
            if not query or query.lower().strip() in name or query.lower().strip() in p.name.lower():
                result_list.append({"name": name, "executable": str(p)})

        return {
            "success": True,
            "count": len(result_list),
            "applications": result_list[:50],
            "message": f"Encontrados {len(result_list)} aplicativos instalados.",
        }

    @classmethod
    def open_application(
        cls,
        app_name: Optional[str] = None,
        application: Optional[str] = None,
        app: Optional[str] = None,
        wait_for_window: bool = True,
        timeout: float = 4.0,
        authorization_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Safely executes a known, validated application and verifies that its GUI window
        actually appears and becomes ready on the Windows desktop.
        Enforces CONFIRM authorization for terminals, shells, and administrative utilities.
        """
        from backend.computer.windows import WindowsService

        target = app_name or application or app or ""
        normalized_app = target.strip().lower()

        # Redirection: Browser / YouTube requests route to persistent BrowserSession
        if normalized_app in ("chrome", "google chrome", "browser", "navegador", "youtube"):
            try:
                from backend.browser.session import get_browser_session
                session = get_browser_session()
                dest_url = "https://www.youtube.com" if "youtube" in normalized_app else "https://www.google.com"
                res = session.open(dest_url)
                return {
                    "success": True,
                    "app": target,
                    "redirected_to_browser_session": True,
                    "url": res.get("url", dest_url),
                    "title": res.get("title", ""),
                    "message": f"Navegador persistente do KON iniciado em '{res.get('url', dest_url)}'.",
                }
            except Exception as e:
                kon_logger.warning(f"[APPLICATIONS] Falha no redirecionamento para BrowserSession: {e}")

        # Check if known or discoverable
        resolved_exe = cls.resolve_application_path(normalized_app)

        if not resolved_exe:
            # Try searching discovered apps
            discovered = cls.discover_installed_applications()
            for k, path in discovered.items():
                if normalized_app in k or k in normalized_app:
                    resolved_exe = path
                    break

        # Check if requested application is restricted (terminal, shell, admin tool)
        is_restricted = (
            normalized_app in cls.RESTRICTED_APPLICATIONS
            or any(r in normalized_app for r in ("powershell", "cmd", "terminal", "prompt", "regedit", "mmc", "pwsh", "wt"))
            or (resolved_exe and resolved_exe.name.lower() in cls.RESTRICTED_BINARIES)
        )
        if is_restricted:
            from backend.security.confirmation_manager import get_confirmation_manager
            cm = get_confirmation_manager()
            # If not validated by token, reject execution
            is_valid = cm.validate_authorization_token("open_application", authorization_token)
            if not is_valid:
                kon_logger.warning(f"[SECURITY] Execução do aplicativo restrito '{target}' bloqueada: requer confirmação explícita.")
                return {
                    "success": False,
                    "app": target,
                    "error": "CONFIRMATION_REQUIRED",
                    "permission_level": "CONFIRM",
                    "message": f"O aplicativo '{target}' é um terminal ou utilitário administrativo do sistema e requer confirmação explícita do usuário para ser executado.",
                }

        if not resolved_exe:
            kon_logger.error(f"Executável para '{target}' não foi encontrado no Windows.")
            return {
                "success": False,
                "app": target,
                "error": "UNAUTHORIZED_OR_UNKNOWN_APPLICATION",
                "message": f"O aplicativo '{target}' não está na lista autorizada do KON ou não foi localizado no seu computador.",
            }

        # Snapshot existing windows before launch
        pre_windows = {w.get("hwnd") for w in WindowsService.list_windows().get("windows", []) if w.get("hwnd")}

        try:
            kon_logger.info(f"Iniciando aplicativo de forma segura: {resolved_exe}")
            safe_env = build_safe_env()
            proc = subprocess.Popen([str(resolved_exe)], env=safe_env, shell=False)

            matched_window = None
            matched_hwnd = None

            # Window readiness verification loop (OBSERVE -> VERIFY)
            if wait_for_window:
                start_wait = time.time()
                while time.time() - start_wait < timeout:
                    time.sleep(0.25)
                    curr_windows = WindowsService.list_windows().get("windows", [])
                    exe_name_lower = resolved_exe.name.lower()

                    for w in curr_windows:
                        hwnd = w.get("hwnd")
                        w_title = (w.get("title") or "").lower()
                        w_proc = (w.get("process") or "").lower()

                        # Check if this is a new window or matches the application
                        if hwnd not in pre_windows or exe_name_lower in w_proc or normalized_app in w_title:
                            matched_window = w.get("title")
                            matched_hwnd = hwnd
                            # Bring newly opened window to focus
                            try:
                                WindowsService.focus_window(w.get("title"))
                            except Exception:
                                pass
                            break

                    if matched_hwnd:
                        break

            # If no window appeared yet, check active window or return process status
            if not matched_window:
                active = WindowsService.get_active_window()
                if normalized_app in (active.get("title") or "").lower():
                    matched_window = active.get("title")
                    matched_hwnd = active.get("hwnd")

            kon_logger.info(f"[APPS] Aplicativo {normalized_app} iniciado com sucesso (Janela: '{matched_window}').")
            return {
                "success": True,
                "app": normalized_app,
                "executable": str(resolved_exe),
                "pid": proc.pid,
                "window": matched_window,
                "hwnd": matched_hwnd,
                "ready": True,
                "message": (
                    f"Aplicativo {target} aberto com sucesso e pronto para uso."
                    if matched_window else
                    f"Aplicativo {target} iniciado com sucesso."
                ),
            }
        except Exception as exc:
            kon_logger.error(f"Erro ao executar processo {resolved_exe}: {exc}")
            return {
                "success": False,
                "app": target,
                "error": str(exc),
                "message": f"Falha ao abrir {target}: {exc}",
            }

    @classmethod
    def close_application(cls, application: str) -> Dict[str, Any]:
        """
        Safely closes running processes of an application using psutil.
        """
        import psutil
        normalized_app = application.strip().lower()
        target_binary = cls.ALLOWED_APPLICATIONS.get(normalized_app)

        if not target_binary:
            resolved = cls.resolve_application_path(normalized_app)
            if resolved:
                target_binary = resolved.name

        if not target_binary:
            target_binary = f"{normalized_app}.exe"

        killed_count = 0
        binary_lower = target_binary.lower()
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == binary_lower:
                    proc.terminate()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if killed_count > 0:
            kon_logger.info(f"[APPS] Encerrado(s) {killed_count} processo(s) de {target_binary}")
            return {
                "success": True,
                "app": normalized_app,
                "processes_closed": killed_count,
                "message": f"Fechando {application}.",
            }
        else:
            return {
                "success": True,
                "app": normalized_app,
                "processes_closed": 0,
                "message": f"Nenhum processo de {application} encontrado em execução.",
            }

    @classmethod
    def switch_window(cls, target: str) -> Dict[str, Any]:
        """Brings an application window to the foreground."""
        from backend.computer.windows import WindowsService
        return WindowsService.focus_window(target)

