"""
Speech-to-Text package for KON.
"""
from voice_assistant.stt.whisper_engine import WhisperSTTEngine, MockSTTEngine, BaseSTTEngine

__all__ = ["WhisperSTTEngine", "MockSTTEngine", "BaseSTTEngine"]
