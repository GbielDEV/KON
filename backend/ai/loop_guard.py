"""
Agent loop guard — detect and prevent degenerate tool-calling loops.
Adapted from OpenJarvis (Apache-2.0 License).
Copyright 2026 OpenJarvis Contributors / Stanford SAIL. Adapted for KON Assistant.
"""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Optional, Set, Dict, Any

from backend.core.events import EventBus, Event
from backend.core.logger import kon_logger


@dataclass(slots=True)
class LoopGuardConfig:
    """Configuration for the loop guard."""
    enabled: bool = True
    max_identical_calls: int = 3      # SHA-256 of (tool_name, arguments)
    ping_pong_window: int = 6         # detect A-B-A-B cycling
    poll_tool_budget: int = 5         # max calls to same polling tool
    warn_before_block: bool = True    # warn on first cycle, block on second


@dataclass(slots=True)
class LoopVerdict:
    """Result of a loop guard check."""
    blocked: bool = False
    reason: str = ""
    warned: bool = False


class LoopGuard:
    """
    Detect and prevent degenerate agent loops in tool execution.

    Features:
    1. Hash tracking: SHA-256 of (tool_name, args) blocks after max_identical_calls.
    2. Ping-pong detection: Sliding window detects A-B-A-B or A-B-C-A-B-C patterns.
    3. Tool budget: Limits excessive executions of the same tool in a single session.
    """

    def __init__(self, config: Optional[LoopGuardConfig] = None, *, bus: Optional[EventBus] = None):
        self._config = config or LoopGuardConfig()
        self._bus = bus
        self._call_counts: Dict[str, int] = {}
        self._tool_sequence: deque[str] = deque(maxlen=self._config.ping_pong_window * 2)
        self._per_tool_counts: Dict[str, int] = {}
        self._warned_cycles: Set[str] = set()

    def check_call(self, tool_name: str, arguments: Any) -> LoopVerdict:
        """Check whether a tool call should proceed or be blocked."""
        if not self._config.enabled:
            return LoopVerdict()

        args_str = json_str if isinstance((json_str := arguments), str) else str(arguments)

        # 1. Hash tracking — identical calls with identical arguments
        call_hash = hashlib.sha256(f"{tool_name}:{args_str}".encode()).hexdigest()[:16]
        self._call_counts[call_hash] = self._call_counts.get(call_hash, 0) + 1

        if self._call_counts[call_hash] > self._config.max_identical_calls:
            reason = (
                f"Chamada idêntica à ferramenta '{tool_name}' repetida "
                f"{self._call_counts[call_hash]} vezes (máximo permitido: {self._config.max_identical_calls})."
            )
            kon_logger.warning(f"[LOOP_GUARD] Bloqueio: {reason}")
            self._emit_triggered("identical_call", tool_name)
            return LoopVerdict(blocked=True, reason=reason)

        # 2. Per-tool budget
        self._per_tool_counts[tool_name] = self._per_tool_counts.get(tool_name, 0) + 1
        if self._per_tool_counts[tool_name] > self._config.poll_tool_budget:
            reason = (
                f"Ferramenta '{tool_name}' excedeu o orçamento máximo "
                f"({self._config.poll_tool_budget} chamadas no ciclo)."
            )
            kon_logger.warning(f"[LOOP_GUARD] Orçamento excedido: {reason}")
            self._emit_triggered("poll_budget", tool_name)
            return LoopVerdict(blocked=True, reason=reason)

        # 3. Ping-pong detection (A-B-A-B)
        self._tool_sequence.append(tool_name)
        if len(self._tool_sequence) >= self._config.ping_pong_window:
            if self._detect_ping_pong():
                reason = "Padrão cíclico repetitivo detectado (ping-pong entre ferramentas)."
                kon_logger.warning(f"[LOOP_GUARD] Padrão ping-pong: {reason}")
                self._emit_triggered("ping_pong", tool_name)
                return LoopVerdict(blocked=True, reason=reason)

        return LoopVerdict()

    def reset(self) -> None:
        """Reset all tracking state between conversational turns."""
        self._call_counts.clear()
        self._tool_sequence.clear()
        self._per_tool_counts.clear()
        self._warned_cycles.clear()

    def _detect_ping_pong(self) -> bool:
        """Detect repeating patterns in tool call sequence."""
        seq = list(self._tool_sequence)
        n = len(seq)
        for period in (2, 3):
            if n >= period * 2:
                tail = seq[-period * 2 :]
                pattern = tail[:period]
                if all(tail[i] == pattern[i % period] for i in range(len(tail))):
                    return True
        return False

    def _emit_triggered(self, reason_type: str, tool_name: str) -> None:
        """Notify EventBus when loop guard triggers."""
        if self._bus:
            try:
                self._bus.publish(
                    Event.error(
                        error_type="LOOP_GUARD_TRIGGERED",
                        message=f"LoopGuard acionado ({reason_type}) na ferramenta {tool_name}",
                        details={"reason_type": reason_type, "tool": tool_name}
                    )
                )
            except Exception:
                pass


__all__ = ["LoopGuard", "LoopGuardConfig", "LoopVerdict"]
