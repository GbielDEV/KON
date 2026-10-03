"""
File Sensitivity Policy — Blocks access to secrets, credentials, environment keys, and sensitive files.
Adapted from OpenJarvis (Apache-2.0 License).
Copyright 2026 OpenJarvis Contributors / Stanford SAIL. Adapted for KON Assistant.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, List, Union

DEFAULT_SENSITIVE_PATTERNS: frozenset[str] = frozenset(
    {
        ".env",
        ".env.*",
        "*.env",
        ".secret",
        "*.secrets",
        "credentials.*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.jks",
        "id_rsa",
        "id_ed25519",
        ".htpasswd",
        ".pgpass",
        ".netrc",
        "id_ecdsa",
        "*.kdbx",
        "id_dsa",
    }
)


def is_sensitive_file(path: Union[str, Path]) -> bool:
    """
    Returns True if path matches any sensitive file pattern or contains secrets.
    Checks filename and path patterns using fnmatch.
    """
    p = Path(path)
    name = p.name
    path_str = str(p).replace("\\", "/")

    for pattern in DEFAULT_SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path_str, pattern):
            return True
        # Check parent folder matches if hidden
        if any(fnmatch.fnmatch(part, pattern) for part in p.parts):
            return True

    return False


def filter_sensitive_paths(paths: Iterable[Union[str, Path]]) -> List[Path]:
    """Return only non-sensitive paths from paths."""
    return [Path(p) for p in paths if not is_sensitive_file(p)]


def validate_file_access(path: Union[str, Path], mode: str = "read") -> bool:
    """
    Validates whether accessing the specified file is permitted.
    Raises PermissionError if the file is sensitive or violates path security.
    """
    if is_sensitive_file(path):
        raise PermissionError(
            f"[SECURITY] Acesso negado: o arquivo '{Path(path).name}' é protegido pela política de segurança de dados do KON."
        )

    from backend.security.path_validator import PathSecurityValidator
    if mode == "read":
        PathSecurityValidator.validate_safe_for_read(path)
    elif mode == "write":
        PathSecurityValidator.validate_safe_for_write(path)
    elif mode == "delete":
        PathSecurityValidator.validate_safe_for_deletion(path)

    return True
