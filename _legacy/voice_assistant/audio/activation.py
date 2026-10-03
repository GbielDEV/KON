"""
Unified Activation Subsystem for KON.
Manages multiple triggers:
- WakeWordActivation ("Okay KON")
- DoubleClapActivation (Two claps acoustic peak detector)
- GestureActivation (Future camera vision hook)
All emit a common activation signal to VoicePipelineOrchestrator.
"""
from abc import ABC, abstractmethod
from typing import Optional, Callable, Dict, Any
import time
import numpy as np

from backend.core.events import EventBus, Event, EventType
from backend.core.logger import kon_logger
from voice_assistant.audio.wake_word import WakeWordDetector


class BaseActivationSource(ABC):
    """Abstract base class for any assistant activation trigger."""

    @abstractmethod
    def process_audio(self, audio_chunk: bytes) -> bool:
        """
        Processes an audio chunk. Returns True if activation trigger detected.
        """
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class WakeWordActivation(BaseActivationSource):
    """Wraps WakeWordDetector ("Okay KON") as an activation source."""

    def __init__(self, detector: WakeWordDetector) -> None:
        self.detector = detector

    def process_audio(self, audio_chunk: bytes) -> bool:
        return self.detector.detect(audio_chunk)

    def start(self) -> None:
        self.detector.start()

    def stop(self) -> None:
        self.detector.stop()


class DoubleClapActivation(BaseActivationSource):
    """
    Real-time Double Clap (duas palmas) acoustic transient detector.
    Evaluates audio energy peaks with deadband suppression and temporal windowing.
    Zero external heavy dependencies; runs in <0.02ms on CPU using numpy.
    """

    def __init__(
        self,
        threshold: int = 14000,
        min_interval_sec: float = 0.15,
        max_interval_sec: float = 0.75,
        enabled: bool = True,
    ) -> None:
        self.threshold = threshold
        self.min_interval_sec = min_interval_sec
        self.max_interval_sec = max_interval_sec
        self.enabled = enabled

        self._first_clap_time: Optional[float] = None
        self._last_detected_time: float = 0.0

    def process_audio(self, audio_chunk: bytes) -> bool:
        if not self.enabled or len(audio_chunk) < 64:
            return False

        now = time.time()

        # Cooldown after a successful trigger (avoid re-triggering during immediate response)
        if now - self._last_detected_time < 2.0:
            return False

        # Convert raw 16-bit PCM bytes to int16 numpy array
        samples = np.frombuffer(audio_chunk, dtype=np.int16)
        peak = int(np.max(np.abs(samples)))

        # 1. If currently waiting for the second clap
        if self._first_clap_time is not None:
            elapsed = now - self._first_clap_time

            # Inside deadband (reverberation of first clap) -> ignore
            if elapsed < self.min_interval_sec:
                return False

            # Exceeded maximum window -> timeout, reset
            if elapsed > self.max_interval_sec:
                self._first_clap_time = None
                # Check if current peak might be a new first clap
                if peak >= self.threshold:
                    self._first_clap_time = now
                return False

            # Within valid window [min_interval, max_interval]
            if peak >= self.threshold:
                kon_logger.info(
                    f"[ACTIVATION] Duas palmas detectadas! (Intervalo: {elapsed * 1000:.1f}ms, Pico: {peak})"
                )
                self._first_clap_time = None
                self._last_detected_time = now
                return True

        # 2. Waiting for the first clap
        elif peak >= self.threshold:
            self._first_clap_time = now

        return False

    def reset(self) -> None:
        self._first_clap_time = None


class ActivationManager:
    """
    Unified coordinator of all activation triggers for KON.
    Monitors wake word, double clap, and future modalities simultaneously.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        wake_word_source: Optional[WakeWordActivation] = None,
        double_clap_source: Optional[DoubleClapActivation] = None,
        on_activated: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.event_bus = event_bus
        self.wake_source = wake_word_source
        self.clap_source = double_clap_source or DoubleClapActivation(enabled=True)
        self.on_activated = on_activated

    def process_audio(self, audio_chunk: bytes) -> Optional[str]:
        """
        Feeds chunk into all active detectors.
        Returns trigger name if any activated ("wake_word", "double_clap", etc.) or None.
        """
        # 1. Check double clap
        if self.clap_source and self.clap_source.process_audio(audio_chunk):
            self._notify_activation("double_clap", {"reason": "Detecção acústica de duas palmas"})
            return "double_clap"

        # 2. Check wake word ("Okay KON")
        if self.wake_source and self.wake_source.process_audio(audio_chunk):
            self._notify_activation("wake_word", {"reason": "Palavra de ativação 'Okay KON'"})
            return "wake_word"

        return None

    def _notify_activation(self, trigger_type: str, details: Dict[str, Any]) -> None:
        kon_logger.info(f"[ACTIVATION] KON Ativado via '{trigger_type}'")

        if self.event_bus:
            # Publish activation event
            self.event_bus.publish(
                Event(
                    type=EventType.STATE_CHANGED,
                    payload={"state": "LISTENING", "trigger": trigger_type, **details},
                )
            )

        if self.on_activated:
            try:
                self.on_activated(trigger_type, details)
            except Exception as exc:
                kon_logger.error(f"[ACTIVATION] Erro no callback de ativação: {exc}")

    def start(self) -> None:
        if self.wake_source:
            self.wake_source.start()
        if self.clap_source:
            self.clap_source.start()

    def stop(self) -> None:
        if self.wake_source:
            self.wake_source.stop()
        if self.clap_source:
            self.clap_source.stop()
