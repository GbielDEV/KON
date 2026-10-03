"""
Unit tests for KON Audio Activation (DoubleClap & ActivationManager).
"""
import time
import numpy as np
from voice_assistant.audio.activation import (
    DoubleClapActivation,
    ActivationManager,
)


def test_double_clap_activation_detection():
    # threshold 1000, intervals suitable for quick unit test
    detector = DoubleClapActivation(threshold=1000, min_interval_sec=0.05, max_interval_sec=0.6)

    # Generate silence chunk (16-bit PCM bytes)
    silence = np.zeros(800, dtype=np.int16).tobytes()

    # Generate clap burst chunk (16-bit PCM bytes)
    clap_samples = np.zeros(800, dtype=np.int16)
    clap_samples[:50] = 5000
    clap_bytes = clap_samples.tobytes()

    assert detector.process_audio(silence) is False
    assert detector.process_audio(clap_bytes) is False  # 1st clap registered

    # Wait for min_interval
    time.sleep(0.06)

    # 2nd clap inside window -> returns True
    assert detector.process_audio(clap_bytes) is True


def test_activation_manager():
    activated_events = []

    def on_act(trigger_type, details):
        activated_events.append((trigger_type, details))

    clap_detector = DoubleClapActivation(threshold=1000, min_interval_sec=0.05, max_interval_sec=0.6)
    manager = ActivationManager(double_clap_source=clap_detector, on_activated=on_act)

    clap_samples = np.zeros(800, dtype=np.int16)
    clap_samples[:50] = 5000
    clap_bytes = clap_samples.tobytes()

    # First clap
    assert manager.process_audio(clap_bytes) is None

    # Wait
    time.sleep(0.06)

    # Second clap
    res = manager.process_audio(clap_bytes)
    assert res == "double_clap"
    assert len(activated_events) == 1
    assert activated_events[0][0] == "double_clap"
