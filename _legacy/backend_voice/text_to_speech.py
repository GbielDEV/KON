"""
Text-to-Speech bridge module.
Delegates to voice_assistant.tts.speak.TextToSpeech.
"""
from typing import Optional, Callable
from backend.core.events import EventBus
from voice_assistant.tts.speak import TextToSpeech


class BaseTextToSpeech:
    def speak(self, text: str, on_complete: Optional[Callable[[], None]] = None) -> None:
        pass

    def stop(self) -> None:
        pass


class WindowsTTS(TextToSpeech, BaseTextToSpeech):
    """
    Backward-compatible WindowsTTS backed by unified TextToSpeech.
    """
    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        super().__init__()
        self.event_bus = event_bus
