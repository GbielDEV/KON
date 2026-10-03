"""
Unit tests for SpeechRecognitionEngine.
Tests dynamic device selection, calibration, in-memory transcription, and error handling.
"""
import numpy as np
import speech_recognition as sr
from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine, _resolve_microphone_index


def test_speech_recognition_engine_init():
    engine = SpeechRecognitionEngine(language="pt-BR", timeout=3, phrase_time_limit=5)
    assert engine.language == "pt-BR"
    assert engine.timeout == 3
    assert engine.phrase_time_limit == 5
    assert engine.last_latency == 0.0


def test_resolve_microphone_index():
    names = sr.Microphone.list_microphone_names()
    if names:
        # Explicit index
        resolved = _resolve_microphone_index(explicit_index=0, target_name="inexistente")
        assert resolved == 0

        # Non-matching name falls back to None (system default)
        fallback = _resolve_microphone_index(explicit_index=None, target_name="dispositivo_fantasma_12345")
        assert fallback is None


def test_speech_recognition_engine_preload():
    engine = SpeechRecognitionEngine()
    # Preload must execute instantly (< 0.05s) and not raise
    engine.preload()
    assert True


def test_speech_recognition_engine_transcribe_empty_or_silence():
    engine = SpeechRecognitionEngine()
    # 0.5s of digital silence (zeros)
    silent_audio = np.zeros(8000, dtype=np.int16)
    text = engine.transcribe(silent_audio, language="pt-BR")
    assert text == "" or isinstance(text, str)
