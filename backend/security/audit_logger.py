"""
Security Audit Logger for the KON Assistant.
Maintains an immutable, queryable audit log in logs/audit_security.jsonl
tracking all tool invocations, security decisions, risk levels, user confirmations,
and execution results without logging credentials or secrets.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from backend.core.logger import kon_logger

AUDIT_LOG_DIR = Path("logs")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit_security.jsonl"


class AuditLogger:
    """
    Structured security and operational audit logger.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = log_path or AUDIT_LOG_FILE
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_arguments(args: Dict[str, Any]) -> Dict[str, Any]:
        """Removes sensitive keys, passwords, or tokens from logged arguments."""
        sanitized = {}
        sensitive_keys = {"password", "secret", "token", "key", "api_key", "auth", "credential"}
        for k, v in args.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, str) and len(v) > 256:
                sanitized[k] = v[:256] + "...[TRUNCATED]"
            else:
                sanitized[k] = v
        return sanitized

    def log_event(
        self,
        tool: str,
        arguments: Dict[str, Any],
        risk_level: str,
        decision: str,  # "ALLOW", "CONFIRM", "DENY"
        confirmation_required: bool,
        user_confirmation: Optional[bool] = None,
        execution_result: Optional[str] = None,
        error: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Appends an audit record to the security log.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epoch": time.time(),
            "tool": tool,
            "arguments": self._sanitize_arguments(arguments),
            "risk_level": risk_level,
            "decision": decision,
            "confirmation_required": confirmation_required,
            "user_confirmation": user_confirmation,
            "execution_result": execution_result,
            "error": error,
            "context": context or {},
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            kon_logger.error(f"[AUDIT] Falha ao gravar log de auditoria: {exc}")

        return entry

    def read_recent_logs(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Reads recent audit records."""
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = []
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                    if len(records) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
            return records
        except Exception as exc:
            kon_logger.error(f"[AUDIT] Falha ao ler logs de auditoria: {exc}")
            return []


# Global singleton instance
_GLOBAL_AUDIT_LOGGER: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _GLOBAL_AUDIT_LOGGER
    if _GLOBAL_AUDIT_LOGGER is None:
        _GLOBAL_AUDIT_LOGGER = AuditLogger()
    return _GLOBAL_AUDIT_LOGGER
