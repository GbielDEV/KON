"""
Wake Word Detection subsystem using openWakeWord.
Completely offline, low CPU usage, decoupled from STT.
Runs continuously while the assistant is in IDLE.
"""
from abc import ABC, abstractmethod
from typing import Optional, Callable, List, Union
import os
import glob
import time
import numpy as np
from backend.core.logger import kon_logger


class WakeWordDetector(ABC):
    """
    Abstract interface for Wake Word detection.
    Interface: detect(frame) -> bool
    """

    def __init__(self, wake_word: str = "Okay KON") -> None:
        self.wake_word = wake_word
        self.is_running = False
        self._callback: Optional[Callable[[], None]] = None

    @abstractmethod
    def start(self, callback: Optional[Callable[[], None]] = None) -> None:
        """Starts wake word listening."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stops wake word listening."""
        pass

    @abstractmethod
    def detect(self, frame: Union[bytes, np.ndarray]) -> bool:
        """
        Processes an incoming audio frame and returns True if wake word is detected.
        """
        pass

    def process_frame(self, frame: Union[bytes, np.ndarray]) -> bool:
        return self.detect(frame)

    def is_active(self) -> bool:
        return self.is_running

    def trigger_mock(self) -> None:
        """Simulates wake word detection for automated unit tests."""
        kon_logger.info(f'[WAKE] Wake word "{self.wake_word}" acionada via teste MOCK.')
        if self._callback and callable(self._callback):
            self._callback()


class OpenWakeWordDetector(WakeWordDetector):
    """
    Real local Wake Word detector powered by openWakeWord ONNX runtime.
    Processes 1280-sample (80ms) 16kHz PCM chunks on CPU.
    """

    CHUNK_SAMPLES = 1280

    def __init__(
        self,
        wake_word: str = "Okay KON",
        threshold: float = 0.38,
        cooldown_seconds: float = 3.0,
        model_paths: Optional[List[str]] = None,
    ) -> None:
        super().__init__(wake_word)
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.model_paths = model_paths
        self._model = None
        self._last_trigger_time = 0.0
        self._active_models: List[str] = []

    def _initialize_model(self) -> None:
        if self._model is not None:
            return

        try:
            import openwakeword
            from openwakeword.model import Model

            models_to_load = []

            # 1. Custom models in data/models
            custom_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "models")
            if os.path.exists(custom_dir):
                custom_models = glob.glob(os.path.join(custom_dir, "*.onnx"))
                if custom_models:
                    models_to_load.extend(custom_models)

            # 2. Explicit paths passed in config
            if self.model_paths:
                models_to_load.extend([p for p in self.model_paths if os.path.exists(p)])

            # 3. Built-in models (alexa, jarvis) to allow dual-recognition
            models_dir = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
            builtins = glob.glob(os.path.join(models_dir, "*.onnx"))
            target_names = ("jarvis", "alexa")
            fallback_models = [
                m for m in builtins
                if any(t in os.path.basename(m).lower() for t in target_names)
            ]
            for m in fallback_models:
                if m not in models_to_load:
                    models_to_load.append(m)

            if models_to_load:
                self._model = Model(wakeword_models=models_to_load, inference_framework="onnx")
                self._active_models = list(self._model.models.keys())
                kon_logger.info(
                    f"[WAKE] Modelos carregados com sucesso: {self._active_models} "
                    f"(threshold: {self.threshold}, wake word: '{self.wake_word}')"
                )
            else:
                kon_logger.warning("[WAKE] Nenhum modelo ONNX de wake word encontrado.")
        except Exception as exc:
            kon_logger.error(f"[WAKE] Erro ao carregar motor openWakeWord: {exc}")
            self._model = None

    def preload(self) -> None:
        """Preloads wake word ONNX model into memory."""
        self._initialize_model()

    def start(self, callback: Optional[Callable[[], None]] = None) -> None:
        self._initialize_model()
        self._callback = callback
        self.is_running = True
        kon_logger.info(f'[WAKE] Detector ativo aguardando wake word "{self.wake_word}".')

    def stop(self) -> None:
        self.is_running = False
        kon_logger.info("[WAKE] Detector de wake word desativado.")

    def detect(self, frame: Union[bytes, np.ndarray]) -> bool:
        """
        Receives raw audio chunk (bytes or int16 numpy array).
        Returns True if wake word crossed threshold.
        """
        if not self.is_running or self._model is None:
            return False

        now = time.time()
        if now - self._last_trigger_time < self.cooldown_seconds:
            return False

        try:
            if isinstance(frame, bytes):
                chunk = np.frombuffer(frame, dtype=np.int16)
            elif isinstance(frame, np.ndarray):
                chunk = frame.astype(np.int16) if frame.dtype != np.int16 else frame
            else:
                return False

            if len(chunk) < self.CHUNK_SAMPLES:
                return False

            # Predict scores with openwakeword
            predictions = self._model.predict(chunk[:self.CHUNK_SAMPLES])

            for model_name, score in predictions.items():
                if score >= self.threshold:
                    self._last_trigger_time = now
                    kon_logger.info(
                        f"[WAKE] Wake word detectada! "
                        f"(Modelo: '{model_name}', Score: {score:.3f} >= {self.threshold})"
                    )
                    if self._callback and callable(self._callback):
                        self._callback()
                    return True

        except Exception as exc:
            kon_logger.debug(f"[WAKE] Erro no processamento de frame: {exc}")

        return False


class MockWakeWordDetector(WakeWordDetector):
    """
    Mock WakeWordDetector for automated tests and isolated validation.
    """

    def start(self, callback: Optional[Callable[[], None]] = None) -> None:
        self._callback = callback
        self.is_running = True
        kon_logger.info(f'[WAKE] Detector Mock iniciado para "{self.wake_word}".')

    def stop(self) -> None:
        self.is_running = False
        kon_logger.info("[WAKE] Detector Mock parado.")

    def detect(self, frame: Union[bytes, np.ndarray]) -> bool:
        return False
