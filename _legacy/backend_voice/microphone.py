"""
Microphone service bridging to voice_assistant.audio.capture.AudioCapture.
Preserves backward compatibility while unifying under a single audio capture pipeline.
"""
from typing import Optional
import numpy as np
from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.simple_capture import SimpleCommandCapture
from voice_assistant.audio.vad import VoiceActivityDetector


class MicrophoneService(AudioCapture):
    """
    MicrophoneService backed directly by AudioCapture from voice_assistant.
    Avoids duplicate audio systems and hardware conflicts.
    """

    def __init__(self, energy_threshold: float = 450.0, device_index: Optional[int] = None) -> None:
        super().__init__(device_index=device_index)
        self.energy_threshold = energy_threshold
        self._vad = VoiceActivityDetector(mode=2, default_silence_timeout=1.5)
        self._simple_capture = SimpleCommandCapture(device_index=device_index)

    def capture_command_simple(
        self,
        max_duration: float = 4.5,
        silence_threshold: float = 400.0,
        silence_duration: float = 1.0,
    ) -> np.ndarray:
        """Captures voice command using the new SimpleCommandCapture module."""
        return self._simple_capture.capture_command(
            max_duration=max_duration,
            silence_threshold=silence_threshold,
            silence_duration=silence_duration,
        )

    def capture_command_speech(
        self,
        max_duration: float = 7.0,
        silence_timeout: float = 1.2,
        initial_timeout: float = 3.5,
    ) -> np.ndarray:
        """Legacy VAD capture kept for backward compatibility."""
        return self._vad.capture_command(
            audio_capture=self,
            max_duration=max_duration,
            silence_timeout=silence_timeout,
            initial_timeout=initial_timeout,
        )

