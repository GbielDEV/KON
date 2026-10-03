"""
Unit tests for SimpleCommandCapture.
Verifies audio parameters, RMS energy calculation, and deterministic command capture.
"""
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voice_assistant.audio.simple_capture import SimpleCommandCapture
from voice_assistant.core.state_machine import VoicePipelineOrchestrator
from voice_assistant.stt.whisper_engine import MockSTTEngine
from backend.core.events import EventBus
from backend.core.state import AssistantState


def test_simple_capture_initialization():
    cap = SimpleCommandCapture()
    assert cap.rate == 16000
    assert cap.channels == 1
    assert cap.chunk == 1024
    assert cap.default_silence_threshold == 400.0
    assert cap.default_silence_duration == 1.0
    assert cap.default_max_duration == 4.0


def test_compute_rms():
    cap = SimpleCommandCapture()

    # Zero audio should produce 0.0 RMS
    silence = bytes(2048)  # 1024 samples of int16 zeros
    assert cap.compute_rms(silence) == 0.0

    # Constant amplitude int16 audio
    samples = np.full(1024, 1000, dtype=np.int16)
    rms = cap.compute_rms(samples.tobytes())
    assert pytest.approx(rms, rel=1e-2) == 1000.0


def test_capture_command_with_mocked_stream():
    cap = SimpleCommandCapture()

    # Create dummy 16-bit PCM frames:
    # 5 speech frames (amplitude 2000), followed by 16 silence frames (amplitude 50)
    speech_chunk = np.full(1024, 2000, dtype=np.int16).tobytes()
    silence_chunk = np.full(1024, 50, dtype=np.int16).tobytes()
    all_chunks = [speech_chunk] * 5 + [silence_chunk] * 20

    mock_stream = MagicMock()
    mock_stream.read.side_effect = all_chunks

    mock_pa = MagicMock()
    mock_pa.open.return_value = mock_stream

    with patch.object(cap, "_get_pyaudio", return_value=mock_pa):
        audio_array = cap.capture_command(
            max_duration=3.0,
            silence_threshold=400.0,
            silence_duration=0.5,
            min_duration=0.1,
            startup_timeout=2.0,
        )

    assert isinstance(audio_array, np.ndarray)
    assert audio_array.dtype == np.float32
    assert len(audio_array) > 0
    # Values should be normalized between -1.0 and 1.0
    assert np.max(np.abs(audio_array)) <= 1.0


def test_orchestrator_integration_with_simple_capture():
    bus = EventBus()
    mock_stt = MockSTTEngine(default_text="abrir navegador")

    # Mock SimpleCommandCapture
    mock_capture = MagicMock(spec=SimpleCommandCapture)
    # Generate 1 second of dummy float32 audio
    dummy_audio = np.full(16000, 0.1, dtype=np.float32)
    mock_capture.capture_command.return_value = dummy_audio

    orch = VoicePipelineOrchestrator(
        event_bus=bus,
        stt_engine=mock_stt,
        command_capture=mock_capture,
    )

    result = orch.run_voice_cycle()

    assert result["success"] is True
    assert result["command"] == "abrir navegador"
    assert orch.state == AssistantState.IDLE
    mock_capture.capture_command.assert_called_once()
