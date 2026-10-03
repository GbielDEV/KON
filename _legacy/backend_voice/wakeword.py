"""
Wake Word bridge module.
Delegates to voice_assistant.audio.wake_word.
"""
from voice_assistant.audio.wake_word import (
    WakeWordDetector,
    OpenWakeWordDetector,
    MockWakeWordDetector,
)

BaseWakeWordDetector = WakeWordDetector
OpenWakeWordRealDetector = OpenWakeWordDetector
CustomModelWakeWordDetector = OpenWakeWordDetector


def create_wake_word_detector(
    engine_type: str = "real",
    wake_word: str = "Okay KON"
) -> WakeWordDetector:
    norm = engine_type.strip().lower()
    if norm in ("real", "openwakeword", "local"):
        return OpenWakeWordDetector(wake_word=wake_word)
    return MockWakeWordDetector(wake_word=wake_word)
