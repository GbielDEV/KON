"""
Structured logging system for KON.
Logs to both logs/kon.log and the central EventBus.
"""
import logging
import re
from typing import Any, Optional
from backend.core.config import get_settings

# Regex pattern for sanitizing potential secrets or tokens
SECRET_PATTERN = re.compile(r"(key|token|secret|password|bearer|auth)[=:\s]+(['\"]?[\w\-\.]{8,}['\"]?)", re.IGNORECASE)


def sanitize_message(message: str) -> str:
    """
    Remove or mask sensitive information such as API keys, tokens, or passwords.
    """
    if not isinstance(message, str):
        message = str(message)
    return SECRET_PATTERN.sub(r"\1=********", message)


class EventBusLogHandler(logging.Handler):
    """
    Logging handler that routes records directly into the EventBus.
    """
    def __init__(self, event_bus: Optional[Any] = None) -> None:
        super().__init__()
        self.event_bus = event_bus

    def emit(self, record: logging.LogRecord) -> None:
        if not self.event_bus:
            return
        try:
            msg = self.format(record)
            safe_msg = sanitize_message(msg)
            from backend.core.events import Event
            event = Event.log(
                level=record.levelname,
                message=safe_msg,
                details={
                    "logger": record.name,
                    "module": record.module,
                    "line": record.lineno
                }
            )
            self.event_bus.publish(event)
        except Exception:
            self.handleError(record)


class KONLogger:
    """
    Central logger wrapper.
    """
    def __init__(self) -> None:
        self.settings = get_settings()
        self.logger = logging.getLogger("KON")
        self.logger.setLevel(logging.DEBUG if self.settings.debug else logging.INFO)
        self.event_bus_handler: Optional[EventBusLogHandler] = None

        self._configure_handlers()

    def _configure_handlers(self) -> None:
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # Formatter
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # File Handler (logs/kon.log)
        try:
            file_handler = logging.FileHandler(
                filename=self.settings.log_file,
                encoding="utf-8",
                mode="a"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception as err:
            print(f"[KONLogger] Failed to initialize FileHandler: {err}")

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # EventBus Handler
        self.event_bus_handler = EventBusLogHandler()
        self.event_bus_handler.setLevel(logging.INFO)
        self.event_bus_handler.setFormatter(formatter)
        self.logger.addHandler(self.event_bus_handler)

    def attach_event_bus(self, event_bus: Any) -> None:
        """
        Connect the logger to the application EventBus.
        """
        if self.event_bus_handler:
            self.event_bus_handler.event_bus = event_bus

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.info(sanitize_message(msg), *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.debug(sanitize_message(msg), *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.warning(sanitize_message(msg), *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.error(sanitize_message(msg), *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.critical(sanitize_message(msg), *args, **kwargs)


kon_logger = KONLogger()


def get_logger() -> KONLogger:
    return kon_logger
