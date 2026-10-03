"""
KON Security Subsystem.
Provides file protection, subprocess isolation, and policy enforcement.
Portions adapted from OpenJarvis (Apache 2.0).
"""
from backend.security.file_policy import is_sensitive_file, filter_sensitive_paths, validate_file_access
from backend.security.subprocess_sandbox import build_safe_env
from backend.security.path_validator import PathSecurityValidator, PathSecurityError
from backend.security.confirmation_manager import ConfirmationManager, get_confirmation_manager, PendingConfirmation, ConfirmationStatus
from backend.security.audit_logger import AuditLogger, get_audit_logger

__all__ = [
    "is_sensitive_file",
    "filter_sensitive_paths",
    "validate_file_access",
    "build_safe_env",
    "PathSecurityValidator",
    "PathSecurityError",
    "ConfirmationManager",
    "get_confirmation_manager",
    "PendingConfirmation",
    "ConfirmationStatus",
    "AuditLogger",
    "get_audit_logger",
]
