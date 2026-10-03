"""
Path Security Validator for KON Assistant.
Provides strict protection against path traversal, symlink attacks,
unauthorized access to critical Windows operating system directories,
and sensitive user credentials.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union, Optional, List

from backend.core.logger import kon_logger
from backend.security.file_policy import is_sensitive_file


class PathSecurityError(PermissionError):
    """Raised when a path violates security policies."""
    pass


class PathSecurityValidator:
    """
    Validates and sanitizes filesystem paths before allowing any file operations.
    Enforces Windows security boundaries and prevents path traversal (..).
    """

    # Protected Windows system folders that should never be written, modified, or deleted by the agent
    PROTECTED_SYSTEM_DIRECTORIES: List[str] = [
        r"C:\Windows",
        r"C:\Windows\System32",
        r"C:\Windows\SysWOW64",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ProgramData\Microsoft",
        r"C:\Recovery",
        r"C:\$Recycle.Bin",
        r"C:\System Volume Information",
        r"C:\Boot",
    ]

    @classmethod
    def get_protected_paths(cls) -> List[Path]:
        """Returns resolved Path objects for all protected system paths."""
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        prog_data = os.environ.get("ProgramData", r"C:\ProgramData")

        candidates = [
            Path(system_root),
            Path(system_root) / "System32",
            Path(prog_files),
            Path(prog_files_x86),
            Path(prog_data) / "Microsoft",
            Path("C:/$Recycle.Bin"),
            Path("C:/Recovery"),
        ]

        resolved = []
        for c in candidates:
            try:
                resolved.append(c.resolve())
            except Exception:
                pass
        return resolved

    @classmethod
    def sanitize_and_resolve(
        cls,
        raw_path: Union[str, Path],
        base_dir: Optional[Union[str, Path]] = None,
        must_exist: bool = False,
    ) -> Path:
        """
        Sanitizes and resolves a path to its canonical absolute form.
        Blocks path traversal sequences and ensures path validity.
        """
        if not raw_path:
            raise PathSecurityError("Caminho não pode ser vazio.")

        path_str = str(raw_path).strip().strip('"').strip("'")

        # 1. Block null bytes and invalid characters in Windows
        if "\0" in path_str:
            raise PathSecurityError("Caminho contém caracteres nulos inválidos.")

        # Normalize bare drive letter like 'C:' to 'C:\'
        if re.match(r"^[A-Za-z]:$", path_str):
            path_str = f"{path_str.upper()}\\"

        # 2. Check for explicit path traversal patterns
        # Matching '..' components that might attempt directory breakout
        parts = Path(path_str).parts
        if ".." in parts:
            kon_logger.warning(f"[SECURITY] Path traversal detectado em: '{path_str}'")
            raise PathSecurityError(f"Caminho inválido: sequência de path traversal ('..') detectada em '{path_str}'.")

        # 3. Resolve path
        try:
            p = Path(path_str)
            if not p.is_absolute():
                if base_dir:
                    base = Path(base_dir).resolve()
                    resolved = (base / p).resolve()
                else:
                    resolved = p.resolve()
            else:
                resolved = p.resolve()
        except Exception as exc:
            raise PathSecurityError(f"Erro ao resolver caminho '{path_str}': {exc}")

        # 4. Check if resolving caused traversal outside base_dir if base_dir was specified
        if base_dir:
            base_resolved = Path(base_dir).resolve()
            try:
                resolved.relative_to(base_resolved)
            except ValueError:
                kon_logger.warning(f"[SECURITY] Tentativa de fuga do diretório base: '{resolved}' fora de '{base_resolved}'")
                raise PathSecurityError(f"Acesso negado: o caminho '{path_str}' escapa do diretório base permitido.")

        # 5. Check existence if required
        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"O caminho '{resolved}' não foi encontrado no sistema.")

        return resolved

    @classmethod
    def validate_safe_for_read(cls, path: Union[str, Path]) -> Path:
        """
        Validates that a path is safe to be read.
        Blocks sensitive files (.env, keys, credentials).
        """
        resolved = cls.sanitize_and_resolve(path, must_exist=True)

        if is_sensitive_file(resolved):
            kon_logger.warning(f"[SECURITY] Tentativa de leitura de arquivo sensível bloqueada: {resolved}")
            raise PathSecurityError(
                f"Acesso negado: o arquivo '{resolved.name}' contém dados sensíveis protegidos pela política do KON."
            )

        return resolved

    @classmethod
    def validate_safe_for_write(cls, path: Union[str, Path], allow_overwrite_system: bool = False) -> Path:
        """
        Validates that a path is safe for creating or modifying files/folders.
        Blocks write operations into Windows OS directories and disk roots.
        """
        resolved = cls.sanitize_and_resolve(path, must_exist=False)

        # 1. Block root of drives (e.g. C:\ or D:\ directly)
        if len(resolved.parts) <= 1 or (len(resolved.parts) == 2 and resolved.parts[1] in ("\\", "/")):
            raise PathSecurityError(f"Operação proibida no diretório raiz da partição: '{resolved}'.")

        # 2. Block sensitive files
        if is_sensitive_file(resolved):
            raise PathSecurityError(f"Não é permitido criar ou modificar arquivos sensíveis protegidos ('{resolved.name}').")

        # 3. Block writing directly inside protected Windows system directories
        if not allow_overwrite_system:
            for protected in cls.get_protected_paths():
                try:
                    resolved.relative_to(protected)
                    kon_logger.warning(f"[SECURITY] Tentativa de escrita em diretório de sistema protegido: '{resolved}' dentro de '{protected}'")
                    raise PathSecurityError(f"Acesso negado: diretório de sistema protegido ('{protected}').")
                except ValueError:
                    # resolved is not inside protected, check next
                    pass

        return resolved

    @classmethod
    def validate_safe_for_deletion(cls, path: Union[str, Path], must_exist: bool = False) -> Path:
        """
        Validates that a path is safe to be deleted.
        Strictest check: blocks system folders, disk roots, user profile root, and sensitive files.
        """
        resolved = cls.sanitize_and_resolve(path, must_exist=False)

        # 1. Prevent deleting root of drives or entire user profile
        user_profile = Path(os.environ.get("USERPROFILE", "C:/Users/Default")).resolve()
        if resolved == user_profile:
            raise PathSecurityError("Operação crítica bloqueada: não é permitido excluir o perfil inteiro do usuário.")

        if len(resolved.parts) <= 1 or resolved.parent == resolved:
            raise PathSecurityError(f"Operação crítica bloqueada: tentativa de exclusão de partição ou raiz: '{resolved}'.")

        # 2. Block protected Windows system directories
        for protected in cls.get_protected_paths():
            try:
                resolved.relative_to(protected)
                raise PathSecurityError(f"Operação crítica bloqueada: tentativa de excluir arquivo/pasta de sistema em '{protected}'.")
            except ValueError:
                pass

        # 3. Block sensitive files
        if is_sensitive_file(resolved):
            raise PathSecurityError(f"Operação bloqueada: o arquivo '{resolved.name}' é protegido pela política de segurança.")

        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"O caminho '{resolved}' não foi encontrado no sistema.")

        return resolved
