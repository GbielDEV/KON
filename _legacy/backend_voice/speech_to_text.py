"""
Speech-to-Text bridge module for KON.
Delegates to voice_assistant.stt.speech_recognition_engine (Google pt-BR via PyAudio) by default,
while maintaining FasterWhisperSTT and MockSpeechToText for backward compatibility.
"""
from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine
from voice_assistant.stt.whisper_engine import (
    BaseSTTEngine,
    WhisperSTTEngine,
    MockSTTEngine,
)

BaseSpeechToText = BaseSTTEngine
SpeechRecognitionSTT = SpeechRecognitionEngine


class FasterWhisperSTT(WhisperSTTEngine):
    """
    Legacy alias for WhisperSTTEngine (kept for rollback / testing).
    """
    def __init__(self, model_size: str = "base", compute_type: str = "int8") -> None:
        super().__init__(model_size=model_size, compute_type=compute_type, default_language="pt")


class MockSpeechToText(MockSTTEngine):
    """
    Backward-compatible mock STT for automated tests.
    """
    def __init__(self, default_response: str = "abra o google chrome") -> None:
        super().__init__(default_text=default_response)
        self.default_response = default_response

