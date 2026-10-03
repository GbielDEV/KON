"""
Text-to-Speech (TTS) package for KON.
Supports multiple engines:
- 'windows' (default): pyttsx3 / Windows SAPI5 — instant, zero RAM cost
- 'kokoro' (optional): Kokoro v1.x neural TTS — human-quality voice, ~500 MB RAM
"""
import os
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from voice_assistant.tts.kokoro_adapter import KokoroTTSAdapter

from voice_assistant.tts.speak import TextToSpeech, falar

__all__ = ["TextToSpeech", "falar", "get_tts_engine"]


def get_tts_engine(engine_name: str = "") -> Union[TextToSpeech, "KokoroTTSAdapter"]:
    """
    Factory function to get the appropriate TTS engine.
    Reads TTS_ENGINE from environment if engine_name not provided.
    Falls back to Windows SAPI5 if Kokoro is not available.
    """
    name = (engine_name or os.environ.get("TTS_ENGINE", "windows")).strip().lower()

    if name == "kokoro":
        try:
            from voice_assistant.tts.kokoro_adapter import KokoroTTSAdapter
            adapter = KokoroTTSAdapter()
            if adapter.is_available:
                return adapter
        except ImportError:
            pass

    # Default: Windows SAPI5
    return TextToSpeech()
