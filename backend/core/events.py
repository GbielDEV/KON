"""
Event schema and EventBus for KON Core.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import asyncio
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """
    Standard event types emitted throughout the KON system.
    """
    STATE_CHANGED = "state_changed"
    LOG = "log"
    TELEMETRY = "telemetry"
    COMMAND = "command"
    SYSTEM_RESPONSE = "system_response"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    ERROR = "error"


class Event(BaseModel):
    """
    Uniform schema for all events dispatched by KON Core.
    """
    type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: Dict[str, Any] = Field(default_factory=dict)
    level: Optional[str] = None
    message: Optional[str] = None

    @classmethod
    def state_changed(cls, state: str, previous_state: Optional[str] = None, description: Optional[str] = None) -> "Event":
        return cls(
            type=EventType.STATE_CHANGED.value,
            data={
                "state": state,
                "previous_state": previous_state,
                "description": description or state
            },
            level="INFO",
            message=f"Estado alterado para {state}"
        )

    @classmethod
    def log(cls, level: str, message: str, details: Optional[Dict[str, Any]] = None) -> "Event":
        return cls(
            type=EventType.LOG.value,
            level=level.upper(),
            message=message,
            data=details or {}
        )

    @classmethod
    def telemetry(cls, telemetry_data: Dict[str, Any]) -> "Event":
        return cls(
            type=EventType.TELEMETRY.value,
            data=telemetry_data
        )

    @classmethod
    def system_response(cls, text: str, success: bool = True, details: Optional[Dict[str, Any]] = None) -> "Event":
        return cls(
            type=EventType.SYSTEM_RESPONSE.value,
            level="INFO" if success else "ERROR",
            message=text,
            data=details or {"success": success}
        )


EventHandler = Callable[[Event], Any]


class EventBus:
    """
    Central event dispatcher supporting both synchronous and asynchronous listeners.
    """
    def __init__(self, max_history: int = 100) -> None:
        self._listeners: Dict[str, List[EventHandler]] = {}
        self._global_listeners: List[EventHandler] = []
        self._history: List[Event] = []
        self._max_history = max_history

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Subscribe to a specific event type.
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        if handler not in self._listeners[event_type]:
            self._listeners[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """
        Subscribe to all dispatched events.
        """
        if handler not in self._global_listeners:
            self._global_listeners.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Unsubscribe from a specific event type.
        """
        if event_type in self._listeners and handler in self._listeners[event_type]:
            self._listeners[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers and record it in recent history.
        """
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Notify specific listeners
        handlers = list(self._listeners.get(event.type, []))
        for handler in handlers:
            self._invoke(handler, event)

        # Notify global listeners
        for handler in list(self._global_listeners):
            self._invoke(handler, event)

    def _invoke(self, handler: EventHandler, event: Event) -> None:
        try:
            res = handler(event)
            if asyncio.iscoroutine(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    res.close()
        except Exception:
            pass

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recent events as dictionaries.
        """
        return [e.model_dump() for e in self._history[-limit:]]
