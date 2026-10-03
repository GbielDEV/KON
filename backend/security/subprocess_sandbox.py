"""
Subprocess Sandbox — Secure process execution with environment isolation for Windows/KON.
Adapted from OpenJarvis (Apache-2.0 License).
Copyright 2026 OpenJarvis Contributors / Stanford SAIL. Adapted for KON Assistant.
"""
from __future__ import annotations

import os
import subprocess
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Safe environment variables to pass through on Windows
_SAFE_ENV_VARS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "COMMONPROGRAMFILES",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "TEMP",
        "TMP",
        "COMSPEC",
        "OS",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
)


@dataclass(slots=True)
class SandboxResult:
    """Result of a sandboxed subprocess execution."""
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    timed_out: bool = False
    killed: bool = False


def build_safe_env(
    passthrough: Optional[List[str]] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Builds a sanitized environment dictionary.
    Excludes sensitive tokens, API keys, and environment variables from leaked subprocesses.
    """
    env: Dict[str, str] = {}
    allowed = _SAFE_ENV_VARS | frozenset(passthrough or [])

    for key, val in os.environ.items():
        if key.upper() in allowed:
            env[key] = val

    if extra:
        env.update(extra)

    return env


def run_safe_command(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: float = 10.0,
    extra_env: Optional[Dict[str, str]] = None,
) -> SandboxResult:
    """
    Executes a command within a sanitized subprocess environment.
    """
    safe_env = build_safe_env(extra=extra_env)

    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return SandboxResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            timed_out=False,
            killed=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning(f"[SECURITY] Comando expirou o tempo limite de {timeout}s: {args}")
        return SandboxResult(
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr or "" if isinstance(exc.stderr, str) else "",
            returncode=-1,
            timed_out=True,
            killed=True,
        )
    except Exception as exc:
        logger.error(f"[SECURITY] Falha ao executar processo seguro: {exc}")
        return SandboxResult(
            stdout="",
            stderr=str(exc),
            returncode=-1,
            timed_out=False,
            killed=False,
        )
