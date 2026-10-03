"""
Voice processing module (Microphone, Wake Word, STT, TTS)
"""
from backend.voice.microphone import MicrophoneService
from backend.voice.wakeword import (
    BaseWakeWordDetector,
    MockWakeWordDetector,
    CustomModelWakeWordDetector,
    create_wake_word_detector,
)
from backend.voice.speech_to_text import (
    BaseSpeechToText,
    FasterWhisperSTT,
    MockSpeechToText,
)
from backend.voice.text_to_speech import (
    BaseTextToSpeech,
    WindowsTTS,
)

__all__ = [
    "MicrophoneService",
    "BaseWakeWordDetector",
    "MockWakeWordDetector",
    "CustomModelWakeWordDetector",
    "create_wake_word_detector",
    "BaseSpeechToText",
    "FasterWhisperSTT",
    "MockSpeechToText",
    "BaseTextToSpeech",
    "WindowsTTS",
]
