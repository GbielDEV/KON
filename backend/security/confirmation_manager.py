"""
Confirmation Manager and Voice Authorization for KON Assistant.
Manages pending confirmation requests, enforces expiration timeouts,
calculates impact summaries, resolves natural language voice responses,
and issues single-use authorization tokens so Gemini can NEVER self-authorize.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Tuple

from backend.core.logger import kon_logger


def normalize_and_hash_args(args: Optional[Dict[str, Any]]) -> str:
    """Computes a deterministic SHA-256 hash of normalized tool arguments."""
    if not args:
        return hashlib.sha256(b"{}").hexdigest()
    filtered = {k: v for k, v in args.items() if k not in ("authorization_token",)}
    canonical_json = json.dumps(filtered, sort_keys=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ConfirmationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class PendingConfirmation:
    """Represents an outstanding action requiring explicit user authorization."""
    confirmation_id: str
    tool: str
    arguments: Dict[str, Any]
    impact_summary: str
    permission_level: str
    args_hash: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 30.0)  # 30 seconds expiration
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    authorization_token: Optional[str] = None
    future: Optional[asyncio.Future] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.confirmation_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "impact_summary": self.impact_summary,
            "permission": self.permission_level,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
        }


class ConfirmationManager:
    """
    Central manager for user confirmations.
    Provides strict lifecycle enforcement for dangerous or impactful actions.
    """

    AFFIRMATIVE_TERMS = frozenset({
        "sim", "pode", "pode fazer", "pode sim", "manda", "manda ver",
        "vai em frente", "confirmo", "confirmar", "confirmado",
        "autorizo", "autorizado", "autoriza", "claro", "com certeza",
        "positivo", "executa", "executar", "pode executar", "prossiga",
    })

    NEGATIVE_TERMS = frozenset({
        "nao", "não", "cancela", "cancelar", "cancelado",
        "esquece", "deixa pra la", "deixa pra lá", "deixa para la", "deixa para lá",
        "para", "parar", "nao faca isso", "não faça isso", "nem pensar",
        "negativo", "aborta", "abortar", "rejeitar", "recusar",
    })

    def __init__(self, default_timeout_seconds: float = 30.0) -> None:
        self.default_timeout = default_timeout_seconds
        self._pending: Dict[str, PendingConfirmation] = {}
        self._active_id: Optional[str] = None  # Most recent outstanding confirmation
        self._valid_tokens: Dict[str, Tuple[str, str, float]] = {}  # token -> (tool_name, args_hash, expires_at)

    def create_confirmation(
        self,
        tool: str,
        arguments: Dict[str, Any],
        impact_summary: str,
        permission_level: str = "CONFIRM",
        timeout_seconds: Optional[float] = None,
    ) -> PendingConfirmation:
        """
        Creates and registers a new pending confirmation.
        """
        self._clean_expired()

        timeout = timeout_seconds or self.default_timeout
        now = time.time()
        conf_id = str(uuid.uuid4())
        args_hash = normalize_and_hash_args(arguments)

        conf = PendingConfirmation(
            confirmation_id=conf_id,
            tool=tool,
            arguments=arguments,
            impact_summary=impact_summary,
            permission_level=permission_level,
            args_hash=args_hash,
            created_at=now,
            expires_at=now + timeout,
            status=ConfirmationStatus.PENDING,
        )

        try:
            loop = asyncio.get_running_loop()
            conf.future = loop.create_future()
        except RuntimeError:
            conf.future = None

        self._pending[conf_id] = conf
        self._active_id = conf_id
        kon_logger.info(
            f"[SECURITY] Nova confirmação pendente criada: {conf_id} ({tool}). Expira em {timeout}s.\n"
            f"  Impacto: {impact_summary}"
        )
        return conf

    def get_pending(self, confirmation_id: str) -> Optional[PendingConfirmation]:
        conf = self._pending.get(confirmation_id)
        if conf and conf.is_expired() and conf.status == ConfirmationStatus.PENDING:
            conf.status = ConfirmationStatus.EXPIRED
        return conf

    def get_active_pending(self) -> Optional[PendingConfirmation]:
        """Returns the currently active pending confirmation if not expired."""
        if not self._active_id:
            return None
        conf = self._pending.get(self._active_id)
        if not conf:
            self._active_id = None
            return None
        if conf.is_expired() and conf.status == ConfirmationStatus.PENDING:
            conf.status = ConfirmationStatus.EXPIRED
            self._active_id = None
            return None
        return conf if conf.status == ConfirmationStatus.PENDING else None

    def parse_natural_consent(
        self,
        text: str,
        sender: str = "User",
        current_state: Optional[str] = None,
        require_active: bool = False,
    ) -> Optional[bool]:
        """
        Parses user's natural language speech or text for confirmation intent.
        Enforces:
        - Only consumes input from User (sender == 'User').
        - Ignores transcriptions during SPEAKING state to prevent KON self-echo.
        - Discards consent if received outside an active pending confirmation window (when require_active=True).
        Returns:
            True  -> Explicitly confirmed ("sim", "pode", "manda", etc.)
            False -> Explicitly rejected ("não", "cancela", "esquece", etc.)
            None  -> Unrelated, ambiguous, or invalid context
        """
        # 1. Protection against non-user input
        if sender and sender.lower() != "user":
            kon_logger.debug(f"[SECURITY] parse_natural_consent ignorado: emissor não é usuário ('{sender}').")
            return None

        # 2. Protection against audio echo during SPEAKING state
        if current_state and current_state.upper() == "SPEAKING":
            kon_logger.debug("[SECURITY] parse_natural_consent ignorado: estado atual é SPEAKING (proteção contra eco).")
            return None

        # 3. Discard consent outside active pending confirmation window
        if require_active and not self.get_active_pending():
            kon_logger.debug("[SECURITY] parse_natural_consent descartado: nenhuma confirmação pendente ativa.")
            return None

        clean = text.strip().lower()
        # Remove punctuation
        clean = re.sub(r"[^\w\s]", "", clean)
        words = set(clean.split())

        # Exact multi-word or single-word matches
        if clean in self.AFFIRMATIVE_TERMS or any(term in clean for term in self.AFFIRMATIVE_TERMS):
            return True

        if clean in self.NEGATIVE_TERMS or any(term in clean for term in self.NEGATIVE_TERMS):
            return False

        # Single word check
        if words.intersection(self.AFFIRMATIVE_TERMS):
            return True
        if words.intersection(self.NEGATIVE_TERMS):
            return False

        return None

    def resolve_confirmation(
        self,
        confirmation_id: Optional[str] = None,
        approved: bool = False,
    ) -> Tuple[bool, Optional[str], str]:
        """
        Resolves a pending confirmation.
        Returns:
            (success, authorization_token, message)
        """
        target_id = confirmation_id or self._active_id
        if not target_id or target_id not in self._pending:
            kon_logger.warning("[SECURITY] Tentativa de resolver confirmação inexistente ou sem ID ativo.")
            return False, None, "Nenhuma confirmação pendente encontrada para esta ação."

        conf = self._pending[target_id]

        # Check expiration
        if conf.is_expired():
            conf.status = ConfirmationStatus.EXPIRED
            if conf.future and not conf.future.done():
                conf.future.set_result(False)
            if self._active_id == target_id:
                self._active_id = None
            kon_logger.warning(f"[SECURITY] Confirmação {target_id} expirou antes de ser respondida.")
            return False, None, "A solicitação de confirmação expirou pelo tempo limite."

        if conf.status != ConfirmationStatus.PENDING:
            return False, None, f"Confirmação já finalizada com status: {conf.status.value}"

        if approved:
            conf.status = ConfirmationStatus.APPROVED
            # Generate single-use authorization token bound to (tool, args_hash)
            token = secrets.token_hex(16)
            conf.authorization_token = token
            # Store valid token with strict 30s lifetime
            self._valid_tokens[token] = (conf.tool, conf.args_hash, time.time() + 30.0)

            if conf.future and not conf.future.done():
                conf.future.set_result(True)

            if self._active_id == target_id:
                self._active_id = None

            kon_logger.info(f"[SECURITY] Confirmação {target_id} ({conf.tool}) APROVADA pelo usuário. Token gerado.")
            return True, token, f"Ação autorizada com sucesso pelo usuário para '{conf.tool}'."
        else:
            conf.status = ConfirmationStatus.REJECTED
            if conf.future and not conf.future.done():
                conf.future.set_result(False)

            if self._active_id == target_id:
                self._active_id = None

            kon_logger.info(f"[SECURITY] Confirmação {target_id} ({conf.tool}) RECUSADA/CANCELADA pelo usuário.")
            return True, None, f"Ação cancelada pelo usuário para '{conf.tool}'."

    def validate_authorization_token(
        self,
        tool_name: str,
        token: Optional[str],
        arguments: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Validates and consumes a single-use authorization token for a given tool and arguments.
        Returns True only if token is valid, matches tool_name, matches args hash (if provided), and has not expired.
        """
        if not token:
            return False

        self._clean_expired_tokens()

        info = self._valid_tokens.get(token)
        if not info:
            kon_logger.warning(f"[SECURITY] Token de autorização inválido ou já utilizado para '{tool_name}'.")
            return False

        expected_tool, expected_hash, expires_at = info
        if time.time() > expires_at:
            self._valid_tokens.pop(token, None)
            kon_logger.warning(f"[SECURITY] Token de autorização para '{tool_name}' expirado (limite 30s).")
            return False

        if expected_tool != tool_name:
            kon_logger.warning(f"[SECURITY] Incompatibilidade de ferramenta no token: esperado '{expected_tool}', recebido '{tool_name}'.")
            return False

        if arguments is not None:
            actual_hash = normalize_and_hash_args(arguments)
            if actual_hash != expected_hash:
                kon_logger.warning(f"[SECURITY] Incompatibilidade de argumentos no token para '{tool_name}': hash esperado '{expected_hash}', recebido '{actual_hash}'.")
                return False

        # Validated successfully — consume token (single-use)
        self._valid_tokens.pop(token, None)
        kon_logger.info(f"[SECURITY] Token de autorização validado com sucesso para '{tool_name}'. Execução permitida.")
        return True

    def _clean_expired(self) -> None:
        now = time.time()
        for cid, conf in list(self._pending.items()):
            if conf.status == ConfirmationStatus.PENDING and now > conf.expires_at:
                conf.status = ConfirmationStatus.EXPIRED
                if conf.future and not conf.future.done():
                    conf.future.set_result(False)
        self._clean_expired_tokens()

    def _clean_expired_tokens(self) -> None:
        now = time.time()
        expired = [tok for tok, (_, _, exp) in self._valid_tokens.items() if now > exp]
        for tok in expired:
            self._valid_tokens.pop(tok, None)


# Singleton instance
_CONFIRMATION_MANAGER: Optional[ConfirmationManager] = None


def get_confirmation_manager() -> ConfirmationManager:
    global _CONFIRMATION_MANAGER
    if _CONFIRMATION_MANAGER is None:
        _CONFIRMATION_MANAGER = ConfirmationManager()
    return _CONFIRMATION_MANAGER
