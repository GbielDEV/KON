"""
File and Directory Management Service for Windows.
Provides safe operations on files, directories, screenshots, and search.
Preserves backward compatibility while delegating core filesystem actions to FileSystemService.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import os
import time
import subprocess

from backend.computer.windows import WindowsService
from backend.computer.system import SystemTelemetry
from backend.computer.filesystem import FileSystemService
from backend.computer.path_resolver import UniversalPathResolver
from backend.core.logger import kon_logger
from backend.security.path_validator import PathSecurityValidator


class FileManager:
    """
    Manages safe operations on the Windows filesystem.
    Delegates deterministic filesystem operations to FileSystemService.
    """

    @classmethod
    def open_folder(cls, folder_identifier: Optional[str] = None, folder: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
        """
        Opens a folder in Windows File Explorer.
        Accepts alias (e.g. 'Downloads', 'Documentos') or absolute path.
        """
        return FileSystemService.open_folder(folder_identifier=folder_identifier, folder=folder, path=path)

    @classmethod
    def create_folder(cls, name: str, parent: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a new folder inside a parent directory (default: Downloads or Documents).
        """
        return FileSystemService.create_folder(name=name, parent=parent)

    @classmethod
    def create_file(cls, path: str, content: str = "") -> Dict[str, Any]:
        """
        Creates a new file with optional content safely.
        """
        return FileSystemService.create_file(path=path, content=content)

    @classmethod
    def search_file(
        cls,
        query: str,
        root: Optional[str] = None,
        extension: Optional[str] = None,
        max_results: int = 5,
    ) -> Dict[str, Any]:
        """
        Searches for files matching query and optional extension.
        Prioritizes direct absolute path verification (Path.exists()) before any scan.
        """
        return FileSystemService.search_file(
            query=query,
            root=root,
            extension=extension,
            max_results=max_results,
        )

    @classmethod
    def check_file_exists(cls, path: str) -> Dict[str, Any]:
        """
        Direct deterministic check for file or directory existence.
        """
        return FileSystemService.check_file_exists(path)

    @classmethod
    def open_file(cls, path: str = "") -> Dict[str, Any]:
        """
        Opens a file using the default OS application.
        Direct absolute paths are verified immediately with Path.exists().
        """
        return FileSystemService.open_file(path)

    @classmethod
    def search_folder(cls, query: str, root: Optional[str] = None) -> Dict[str, Any]:
        """
        Searches for a folder by name or alias.
        """
        search_roots = [root] if root else None
        return UniversalPathResolver.resolve_path(
            query,
            expected_type="directory",
            allow_search=True,
            search_roots=search_roots,
        )

    @classmethod
    def check_path(cls, path: str) -> Dict[str, Any]:
        """
        Direct deterministic check whether a path exists.
        """
        return FileSystemService.check_file_exists(path)

    @classmethod
    def get_file_info(cls, path: str) -> Dict[str, Any]:
        """
        Returns structured metadata for a file.
        """
        return FileSystemService.check_file_exists(path)

    @classmethod
    def get_folder_info(cls, path: str) -> Dict[str, Any]:
        """
        Returns structured metadata for a folder.
        """
        return FileSystemService.check_file_exists(path)

    @classmethod
    def move_file(cls, source: str, destination: str) -> Dict[str, Any]:
        """
        Moves a file to a new destination folder or path.
        """
        return FileSystemService.move_file(source, destination)

    @classmethod
    def copy_file(cls, source: str, destination: str) -> Dict[str, Any]:
        """
        Copies a file to a new destination folder or path.
        """
        return FileSystemService.copy_file(source, destination)

    @classmethod
    def rename_file(cls, path: str, new_name: str) -> Dict[str, Any]:
        """
        Renames a file or directory.
        """
        return FileSystemService.rename_file(path, new_name)

    @classmethod
    def delete_file(cls, path: str) -> Dict[str, Any]:
        """
        Deletes a file or directory after verifying file security policy.
        """
        return FileSystemService.delete_file(path)

    @classmethod
    def read_file(cls, path: str, max_bytes: int = 65536) -> Dict[str, Any]:
        """
        Reads a text file securely, enforcing the security file policy.
        """
        return FileSystemService.read_file(path, max_bytes=max_bytes)

    @classmethod
    def write_file(cls, path: str, content: str) -> Dict[str, Any]:
        """
        Writes to a text file securely, enforcing the security file policy.
        """
        return FileSystemService.write_file(path, content)

    @classmethod
    def list_directory(cls, path: Optional[str] = None) -> Dict[str, Any]:
        """
        Lists items in a directory securely, excluding sensitive files.
        Accepts path or folder alias (e.g. 'Downloads', 'Documentos').
        """
        return FileSystemService.list_directory(path)

    @classmethod
    def calculate_deletion_impact(cls, path: str) -> Dict[str, Any]:
        """
        Calculates the potential blast radius of deleting a file or directory.
        Returns file count, total size in MB/GB, whether it's permanent, and risk level.
        """
        try:
            p = FileSystemService.normalize_path_input(path)
            if not p or not p.exists():
                return {
                    "exists": False,
                    "file_count": 0,
                    "total_size_bytes": 0,
                    "risk_level": "CONFIRM",
                    "impact_summary": f"O arquivo ou pasta '{path}' não existe.",
                }

            PathSecurityValidator.validate_safe_for_deletion(p)

            if p.is_file():
                size = p.stat().st_size
                size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
                return {
                    "exists": True,
                    "is_directory": False,
                    "path": str(p),
                    "file_count": 1,
                    "total_size_bytes": size,
                    "risk_level": "CONFIRM",
                    "impact_summary": f"A ação excluirá o arquivo '{p.name}' ({size_str}) permanentemente.",
                }
            else:
                file_count = 0
                dir_count = 0
                total_size = 0
                for root, dirs, files in os.walk(str(p)):
                    dir_count += len(dirs)
                    for f in files:
                        file_count += 1
                        fp = Path(root) / f
                        try:
                            total_size += fp.stat().st_size
                        except Exception:
                            pass

                if total_size >= 1024 * 1024 * 1024:
                    size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"
                elif total_size >= 1024 * 1024:
                    size_str = f"{total_size / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{total_size / 1024:.1f} KB"

                risk = "CRITICAL" if file_count > 5 or dir_count > 1 else "CONFIRM"
                summary = (
                    f"Encontrei {file_count} arquivo(s) na pasta '{p.name}', "
                    f"totalizando aproximadamente {size_str}. "
                    f"A ação solicitada excluirá todos eles permanentemente. Deseja continuar?"
                )

                return {
                    "exists": True,
                    "is_directory": True,
                    "path": str(p),
                    "file_count": file_count,
                    "dir_count": dir_count,
                    "total_size_bytes": total_size,
                    "risk_level": risk,
                    "impact_summary": summary,
                }
        except Exception as exc:
            return {
                "exists": False,
                "error": str(exc),
                "risk_level": "CRITICAL",
                "impact_summary": f"Aviso de segurança: {exc}",
            }

    @classmethod
    def take_screenshot(cls, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Captures full screen and saves to Pictures/Screenshots or Pictures.
        """
        try:
            save_dir = WindowsService.get_pictures_dir() / "Screenshots"
            save_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            target_path = Path(output_path) if output_path else save_dir / f"screenshot_{timestamp}.png"

            # Use PowerShell Windows.Forms / Drawing for native zero-dependency screenshot
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
            res = subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=5)
            if res.returncode == 0 and target_path.exists():
                return {
                    "success": True,
                    "path": str(target_path),
                    "message": f"Print da tela capturado e salvo em {target_path.name}."
                }
            else:
                return {
                    "success": False,
                    "error": "SCREENSHOT_FAILED",
                    "message": "Não foi possível capturar a tela."
                }
        except Exception as err:
            kon_logger.error(f"[FILES] Falha ao tirar screenshot: {err}")
            return {"success": False, "error": str(err), "message": f"Erro ao tirar print: {err}"}

    @classmethod
    def format_system_info(cls, metric: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns structured telemetry and spoken text for system_info tool.
        """
        cpu = SystemTelemetry.get_cpu_percent()
        ram = SystemTelemetry.get_ram_info()
        uptime_sec = SystemTelemetry.get_uptime_seconds()
        uptime_fmt = SystemTelemetry.format_uptime(uptime_sec)

        clean_metric = (metric or "").strip().lower()
        if clean_metric in ("ram", "memory", "memoria"):
            msg = f"O uso de memória RAM está em {ram['percent']}%, sendo {ram['used_gb']} GB usados de um total de {ram['total_gb']} GB."
        elif clean_metric in ("cpu", "processador"):
            msg = f"O uso do processador está em {cpu}%."
        elif clean_metric in ("uptime", "tempo"):
            msg = f"O assistente está ativo há {uptime_fmt}."
        elif clean_metric in ("time", "hora", "horas"):
            now_time = time.strftime("%H:%M")
            msg = f"Agora são {now_time}."
        else:
            msg = f"O sistema está com {cpu}% de CPU e {ram['percent']}% de memória RAM em uso."

        return {
            "success": True,
            "cpu_percent": cpu,
            "ram_percent": ram["percent"],
            "ram_used_gb": ram["used_gb"],
            "ram_total_gb": ram["total_gb"],
            "uptime": uptime_fmt,
            "message": msg,
        }
