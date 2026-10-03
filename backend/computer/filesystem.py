"""
Filesystem Service for KON Assistant.
Provides deterministic, secure, and structured file and directory management on Windows OS:
- Direct absolute path verification (Path.exists()) has top priority before any scanning.
- Robust normalization of drive letters (C:\\, D:\\, E:\\), quotes, slashes, spaces, and user aliases.
- Multi-drive and user folder search with fuzzy matching fallback.
- Standardized structured JSON responses for all operations.
- Full enforcement of KON security file policy and PathSecurityValidator.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from backend.computer.windows import WindowsService
from backend.computer.path_resolver import (
    UniversalPathResolver,
    PathNormalizer,
    DriveManager,
    WindowsKnownFolders,
    SmartPathSearcher,
)
from backend.core.logger import kon_logger
from backend.security.file_policy import is_sensitive_file, validate_file_access
from backend.security.path_validator import PathSecurityValidator, PathSecurityError


class FileSystemService:
    """
    Deterministic Filesystem management service for KON.
    Enforces absolute-path priority, structured output schemas, and strict security validation.
    """

    @classmethod
    def normalize_path_input(cls, raw_path: Union[str, Path, None]) -> Optional[Path]:
        """
        Normalizes arbitrary user/model path strings into a valid, canonical Path object:
        - Strips surrounding quotes, whitespace, and clean backslashes.
        - Expands environment variables (%USERPROFILE%, %APPDATA%, ~).
        - Fixes bare drive letters like 'c:' or 'c' to 'C:\\'.
        - Resolves relative folder aliases ('downloads', 'documentos', 'desktop').
        """
        if raw_path is None:
            return None

        clean_str = str(raw_path).strip().strip('"').strip("'")
        if not clean_str:
            return None

        # Check special folder aliases first (e.g. 'Downloads', 'Área de Trabalho')
        alias_resolved = WindowsService.resolve_folder_alias(clean_str)
        if alias_resolved and alias_resolved.exists():
            return alias_resolved

        norm = PathNormalizer.normalize_path_str(clean_str)
        if not norm:
            return None

        try:
            p = Path(norm)
            return p
        except Exception:
            return None

    @classmethod
    def get_structured_file_info(cls, path_obj: Path, resolution_method: str = "explicit_path") -> Dict[str, Any]:
        """
        Returns the standardized structured information dictionary for an existing file or directory.
        Delegates to UniversalPathResolver.format_path_info.
        """
        return UniversalPathResolver.format_path_info(path_obj, resolution_method=resolution_method)

    @classmethod
    def check_file_exists(cls, path: str) -> Dict[str, Any]:
        """
        Direct deterministic check for file or directory existence.
        Returns immediate structured result without disk scanning.
        """
        path_obj = cls.normalize_path_input(path)
        if not path_obj:
            return {
                "found": False,
                "success": False,
                "requested_path": path,
                "reason": "invalid_path",
                "message": f"O caminho '{path}' é inválido.",
            }

        try:
            if path_obj.exists():
                info = cls.get_structured_file_info(path_obj, resolution_method="explicit_path")
                info["message"] = f"{info['type'].capitalize()} '{info['name']}' existe em '{info['parent']}'."
                return info
            else:
                return {
                    "found": False,
                    "success": False,
                    "requested_path": str(path_obj),
                    "reason": "path_not_found",
                    "message": f"O caminho '{path_obj}' não existe no computador.",
                }
        except Exception as exc:
            return {
                "found": False,
                "success": False,
                "requested_path": str(path_obj),
                "reason": "error",
                "message": f"Erro ao verificar caminho '{path_obj}': {exc}",
            }

    @classmethod
    def search_file(
        cls,
        query: str,
        root: Optional[str] = None,
        extension: Optional[str] = None,
        max_results: int = 5,
        search_subfolders: bool = True,
        max_depth: int = 4,
    ) -> Dict[str, Any]:
        """
        Searches for a file with mandatory ABSOLUTE PATH PRIORITY:
        1. If query is a direct absolute path or points to an existing file/folder, returns immediately.
        2. If query specifies a direct path that does NOT exist, explicitly states that the path does not exist.
        3. If query is a filename/term, scans root directory or accessible drives and user directories.
        4. Supports fuzzy name matching, speech-to-text typo tolerance, and disambiguation.
        """
        clean_query = (query or "").strip().strip('"').strip("'")
        if not clean_query:
            return {
                "found": False,
                "success": False,
                "requested_path": query,
                "reason": "empty_query",
                "message": "Nenhum nome de arquivo ou termo foi especificado para a busca.",
            }

        kon_logger.info(f"[FILESYSTEM] search_file chamado: query='{clean_query}', root='{root}', ext='{extension}'")

        # -------------------------------------------------------------
        # STEP 1: Direct Path Priority Check (Path.exists())
        # -------------------------------------------------------------
        has_path_separators = ("\\" in clean_query or "/" in clean_query or ":" in clean_query)
        normalized_direct = cls.normalize_path_input(clean_query)

        if normalized_direct and (has_path_separators or normalized_direct.is_absolute()):
            if normalized_direct.exists():
                info = cls.get_structured_file_info(normalized_direct, resolution_method="explicit_path")
                info["message"] = f"Arquivo encontrado diretamente em '{info['path']}'."
                info["results"] = [info.copy()]
                info["count"] = 1
                kon_logger.info(f"[FILESYSTEM] Caminho direto confirmado com Path.exists(): {info['path']}")
                return info
            else:
                if normalized_direct.is_absolute():
                    searched_locs = [str(normalized_direct.parent)]
                    kon_logger.warning(f"[FILESYSTEM] Caminho absoluto solicitado não existe: {normalized_direct}")
                    return {
                        "found": False,
                        "success": True,
                        "requested_path": str(normalized_direct),
                        "reason": "path_not_found",
                        "searched_roots": searched_locs,
                        "results": [],
                        "count": 0,
                        "message": (
                            f"O caminho exato '{normalized_direct}' não existe no computador. "
                            f"A pasta '{normalized_direct.parent}' foi verificada."
                        ),
                    }

        # -------------------------------------------------------------
        # STEP 2: Universal Resolution & Search
        # -------------------------------------------------------------
        search_roots_list = [root] if root else None
        res = UniversalPathResolver.resolve_path(
            clean_query,
            expected_type=None,
            allow_search=True,
            search_roots=search_roots_list,
            extension=extension,
        )

        if res.get("disambiguation_required"):
            return res

        if res.get("found"):
            if "results" not in res:
                res["results"] = [res.copy()]
            if "count" not in res:
                res["count"] = len(res.get("results", []))
            return res
        else:
            return res

    @classmethod
    def open_file(cls, path: str = "") -> Dict[str, Any]:
        """
        Opens a file using the default OS application after strict safety validation.
        Follows UniversalPathResolver hierarchy:
        1. Resolve path (explicit, relative, known folder, alias, or search)
        2. Verify existence & is_file
        3. Verify permissions (SAFE)
        4. Identify extension
        5. Open using Windows default application
        6. Verify opening
        7. Return structured result
        """
        clean_path = (path or "").strip()
        if not clean_path:
            last_f = UniversalPathResolver.get_last_found_file()
            if last_f:
                clean_path = str(last_f)
            else:
                return {
                    "found": False,
                    "success": False,
                    "error": "EMPTY_PATH",
                    "message": "Caminho do arquivo não fornecido.",
                }

        res = UniversalPathResolver.resolve_path(clean_path, expected_type="file", allow_search=True)

        if res.get("disambiguation_required"):
            return res

        if not res.get("found") or not res.get("path"):
            return {
                "found": False,
                "success": False,
                "error": "FILE_NOT_FOUND",
                "requested_path": clean_path,
                "reason": res.get("reason", "path_not_found"),
                "searched_roots": res.get("searched_roots", []),
                "message": res.get("message") or f"Arquivo '{clean_path}' não foi encontrado no computador.",
            }

        path_obj = Path(res["path"])
        if path_obj.is_dir():
            return cls.open_folder(folder=str(path_obj))

        try:
            validate_file_access(path_obj, mode="read")
            kon_logger.info(f"[FILESYSTEM] Opening: {path_obj}")
            os.startfile(str(path_obj))
            info = UniversalPathResolver.format_path_info(
                path_obj,
                resolution_method=res.get("resolution_method", "explicit_path"),
                message=f"Abrindo o arquivo '{path_obj.name}'."
            )
            info["success"] = True
            return info
        except PermissionError as p_err:
            return {
                "found": True,
                "success": False,
                "error": "SECURITY_BLOCK",
                "path": str(path_obj),
                "resolution_method": res.get("resolution_method", "explicit_path"),
                "message": str(p_err),
            }
        except Exception as err:
            kon_logger.error(f"[FILESYSTEM] Erro ao abrir arquivo {path_obj}: {err}")
            return {
                "found": True,
                "success": False,
                "error": str(err),
                "path": str(path_obj),
                "resolution_method": res.get("resolution_method", "explicit_path"),
                "message": f"Falha ao abrir arquivo: {err}",
            }

    @classmethod
    def open_folder(
        cls,
        folder_identifier: Optional[str] = None,
        folder: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Opens a folder in Windows File Explorer.
        Resolves real configured path for Windows Known Folders (Downloads, Documents, Desktop, etc.),
        drive roots (C:\\, D:\\, E:\\), user directories, and absolute paths.
        """
        target_str = folder_identifier or folder or path or "Downloads"
        res = UniversalPathResolver.resolve_path(target_str, expected_type="directory", allow_search=True)

        if not res.get("found") or not res.get("path"):
            return {
                "found": False,
                "success": False,
                "error": "FOLDER_NOT_FOUND",
                "requested_path": target_str,
                "reason": res.get("reason", "folder_not_found"),
                "searched_roots": res.get("searched_roots", []),
                "message": f"Pasta '{target_str}' não foi encontrada ou não é um diretório válido.",
            }

        resolved_path = Path(res["path"])
        if not resolved_path.is_dir():
            resolved_path = resolved_path.parent

        try:
            kon_logger.info(f"[FILESYSTEM] Opening: {resolved_path}")
            os.startfile(str(resolved_path))
            info = UniversalPathResolver.format_path_info(
                resolved_path,
                resolution_method=res.get("resolution_method", "explicit_path"),
                message=f"Abrindo a pasta '{resolved_path.name or str(resolved_path)}'."
            )
            info["success"] = True
            return info
        except Exception as err:
            kon_logger.error(f"[FILESYSTEM] Erro ao abrir pasta {resolved_path}: {err}")
            return {
                "found": True,
                "success": False,
                "error": str(err),
                "path": str(resolved_path),
                "message": f"Erro ao tentar abrir pasta {target_str}: {err}",
            }

    @classmethod
    def list_directory(
        cls,
        path: Optional[str] = None,
        show_hidden: bool = False,
        max_items: int = 100,
    ) -> Dict[str, Any]:
        """
        Lists files and directories in a given path (including drive roots C:\\, D:\\, E:\\).
        Returns structured item details.
        """
        target = path or "Downloads"
        resolved_path = cls.normalize_path_input(target)

        if not resolved_path:
            return {
                "found": False,
                "success": False,
                "error": "INVALID_PATH",
                "message": f"Caminho '{path}' inválido.",
            }

        try:
            safe_resolved = PathSecurityValidator.sanitize_and_resolve(resolved_path, must_exist=True)
            if not safe_resolved.is_dir():
                return {
                    "found": True,
                    "success": False,
                    "error": "NOT_A_DIRECTORY",
                    "path": str(safe_resolved),
                    "message": f"'{safe_resolved}' não é um diretório.",
                }

            items: List[Dict[str, Any]] = []
            for item in safe_resolved.iterdir():
                if not show_hidden and item.name.startswith("."):
                    continue
                if is_sensitive_file(item):
                    continue

                try:
                    is_d = item.is_dir()
                    sz = item.stat().st_size if not is_d else 0
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if is_d else "file",
                        "size": sz,
                        "extension": item.suffix.lower() if not is_d else "",
                    })
                except Exception:
                    continue

                if len(items) >= max_items:
                    break

            return {
                "found": True,
                "success": True,
                "path": str(safe_resolved),
                "name": safe_resolved.name or str(safe_resolved),
                "count": len(items),
                "items": items,
                "message": f"A pasta '{safe_resolved.name or str(safe_resolved)}' contém {len(items)} item(ns).",
            }
        except (PathSecurityError, PermissionError) as p_err:
            return {"found": False, "success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except FileNotFoundError:
            return {
                "found": False,
                "success": False,
                "error": "FOLDER_NOT_FOUND",
                "requested_path": target,
                "reason": "path_not_found",
                "message": f"A pasta '{target}' não foi encontrada.",
            }
        except Exception as err:
            return {"found": False, "success": False, "error": str(err), "message": f"Erro ao listar pasta: {err}"}

    @classmethod
    def create_folder(cls, name: str, parent: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a new folder inside a parent directory (defaults to Downloads).
        """
        if not name or not name.strip():
            return {"success": False, "error": "EMPTY_FOLDER_NAME", "message": "O nome da pasta não pode ser vazio."}

        clean_name = name.strip()
        parent_dir = cls.normalize_path_input(parent) if parent else WindowsService.get_downloads_dir()
        if not parent_dir or not parent_dir.exists():
            parent_dir = WindowsService.get_downloads_dir()

        target_folder = parent_dir / clean_name

        try:
            validate_file_access(target_folder, mode="write")
            target_folder.mkdir(parents=True, exist_ok=True)
            kon_logger.info(f"[FILESYSTEM] Pasta criada: {target_folder}")
            info = cls.get_structured_file_info(target_folder)
            info["success"] = True
            info["message"] = f"Pasta '{clean_name}' criada com sucesso em '{parent_dir.name}'."
            return info
        except PermissionError as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            kon_logger.error(f"[FILESYSTEM] Erro ao criar pasta {target_folder}: {err}")
            return {"success": False, "error": str(err), "message": f"Erro ao criar pasta: {err}"}

    @classmethod
    def create_file(cls, path: str, content: str = "") -> Dict[str, Any]:
        """
        Creates a new file with optional text content safely.
        """
        try:
            resolved = PathSecurityValidator.validate_safe_for_write(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            kon_logger.info(f"[FILESYSTEM] Arquivo criado: {resolved}")
            info = cls.get_structured_file_info(resolved)
            info["success"] = True
            info["message"] = f"Arquivo '{resolved.name}' criado com sucesso."
            return info
        except (PathSecurityError, PermissionError) as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            kon_logger.error(f"[FILESYSTEM] Erro ao criar arquivo '{path}': {err}")
            return {"success": False, "error": str(err), "message": f"Erro ao criar arquivo: {err}"}

    @classmethod
    def move_file(cls, source: str, destination: str) -> Dict[str, Any]:
        """
        Moves a file or directory to a destination path.
        """
        src = cls.normalize_path_input(source)
        if not src or not src.exists():
            s_res = cls.search_file(source, max_results=1)
            if s_res.get("found"):
                src = Path(s_res["path"])
            else:
                return {
                    "success": False,
                    "error": "SOURCE_NOT_FOUND",
                    "reason": "path_not_found",
                    "message": f"Arquivo de origem '{source}' não encontrado.",
                }

        dest_dir = cls.normalize_path_input(destination)
        if dest_dir and dest_dir.exists() and dest_dir.is_dir():
            dest = dest_dir / src.name
        else:
            dest = cls.normalize_path_input(destination) or Path(destination)

        try:
            validate_file_access(src, mode="read")
            validate_file_access(dest, mode="write")
            shutil.move(str(src), str(dest))
            kon_logger.info(f"[FILESYSTEM] Arquivo movido de {src} para {dest}")
            return {
                "success": True,
                "source": str(src),
                "destination": str(dest),
                "name": dest.name,
                "message": f"Arquivo '{src.name}' movido com sucesso para '{dest.parent.name}'.",
            }
        except PermissionError as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err), "message": f"Erro ao mover arquivo: {err}"}

    @classmethod
    def copy_file(cls, source: str, destination: str) -> Dict[str, Any]:
        """
        Copies a file to a destination path.
        """
        try:
            src = PathSecurityValidator.validate_safe_for_read(source)
            dest_dir = cls.normalize_path_input(destination)
            if dest_dir and dest_dir.exists() and dest_dir.is_dir():
                dest = dest_dir / src.name
            else:
                dest = cls.normalize_path_input(destination) or Path(destination)
            dest = PathSecurityValidator.validate_safe_for_write(dest)

            shutil.copy2(str(src), str(dest))
            kon_logger.info(f"[FILESYSTEM] Arquivo copiado de {src} para {dest}")
            return {
                "success": True,
                "source": str(src),
                "destination": str(dest),
                "name": dest.name,
                "message": f"Arquivo '{src.name}' copiado para '{dest.parent.name}'.",
            }
        except (PathSecurityError, PermissionError) as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err), "message": f"Erro ao copiar arquivo: {err}"}

    @classmethod
    def rename_file(cls, path: str, new_name: str) -> Dict[str, Any]:
        """
        Renames a file or directory.
        """
        p = cls.normalize_path_input(path)
        if not p or not p.exists():
            s_res = cls.search_file(path, max_results=1)
            if s_res.get("found"):
                p = Path(s_res["path"])
            else:
                return {
                    "success": False,
                    "error": "PATH_NOT_FOUND",
                    "reason": "path_not_found",
                    "message": f"Arquivo '{path}' não encontrado.",
                }

        dest = p.parent / new_name.strip()
        try:
            validate_file_access(p, mode="write")
            validate_file_access(dest, mode="write")
            p.rename(dest)
            return {
                "success": True,
                "old_name": p.name,
                "new_name": dest.name,
                "path": str(dest),
                "message": f"Arquivo renomeado para '{dest.name}'.",
            }
        except PermissionError as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err), "message": f"Erro ao renomear arquivo: {err}"}

    @classmethod
    def delete_file(cls, path: str) -> Dict[str, Any]:
        """
        Safely deletes a file or directory with security policy enforcement.
        """
        p = cls.normalize_path_input(path)
        if not p or not p.exists():
            s_res = cls.search_file(path, max_results=1)
            if s_res.get("found"):
                p = Path(s_res["path"])
            else:
                return {
                    "success": False,
                    "error": "FILE_NOT_FOUND",
                    "reason": "path_not_found",
                    "message": f"Arquivo ou pasta '{path}' não encontrado.",
                }

        try:
            PathSecurityValidator.validate_safe_for_deletion(p)
            if p.is_dir():
                shutil.rmtree(str(p))
                kon_logger.info(f"[FILESYSTEM] Diretório excluído: {p}")
                return {
                    "success": True,
                    "path": str(p),
                    "is_directory": True,
                    "message": f"Pasta '{p.name}' excluída com sucesso.",
                }
            else:
                p.unlink()
                kon_logger.info(f"[FILESYSTEM] Arquivo excluído: {p}")
                return {
                    "success": True,
                    "path": str(p),
                    "is_directory": False,
                    "message": f"Arquivo '{p.name}' excluído com sucesso.",
                }
        except (PathSecurityError, PermissionError) as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err), "message": f"Erro ao excluir arquivo: {err}"}

    @classmethod
    def read_file(cls, path: str, max_bytes: int = 65536) -> Dict[str, Any]:
        """
        Reads text content securely.
        """
        try:
            validate_file_access(path, mode="read")
            p = cls.normalize_path_input(path)
            if not p or not p.exists() or not p.is_file():
                return {"success": False, "error": f"Arquivo '{path}' não encontrado."}
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            return {"success": True, "path": str(p), "name": p.name, "content": content}
        except PermissionError as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err)}

    @classmethod
    def write_file(cls, path: str, content: str) -> Dict[str, Any]:
        """
        Writes text content securely.
        """
        try:
            validate_file_access(path, mode="write")
            p = PathSecurityValidator.validate_safe_for_write(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": str(p), "name": p.name, "message": f"Arquivo '{p.name}' salvo com sucesso."}
        except PermissionError as p_err:
            return {"success": False, "error": "SECURITY_BLOCK", "message": str(p_err)}
        except Exception as err:
            return {"success": False, "error": str(err)}
