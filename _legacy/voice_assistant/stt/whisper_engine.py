"""
Speech-to-Text (STT) Engine using faster-whisper.
Configured for model 'small', CPU, int8 quantization, and Brazilian Portuguese.
Single-instance caching ensures memory stability on 8 GB RAM machines.
"""
from abc import ABC, abstractmethod
from typing import Union, Optional
import time
import threading
import numpy as np
from backend.core.logger import kon_logger


class BaseSTTEngine(ABC):
    """
    Abstract interface for STT engines.
    """

    @abstractmethod
    def transcribe(self, audio: Union[np.ndarray, bytes, str], language: str = "pt") -> str:
        """
        Transcribes audio into text.
        """
        pass

    @property
    @abstractmethod
    def last_latency(self) -> float:
        """
        Last transcription latency in seconds.
        """
        pass

    def preload(self) -> None:
        """
        Preloads model weights and allocates inference buffers.
        """
        pass


def _resolve_compute_type(device: str, compute_type: str) -> str:
    """
    Picks a CTranslate2 compute type supported by the host machine/device.
    Adapted from OpenJarvis (Apache-2.0).
    """
    try:
        import ctranslate2
        supported = set(ctranslate2.get_supported_compute_types(device))
    except Exception:
        return compute_type

    if compute_type in supported:
        return compute_type

    preferences = (
        ("int8", "float32", "int8_float32", "int16")
        if compute_type in ("float16", "int8")
        else ("float32", "int8", "int8_float32", "int16")
    )
    fallback = next((val for val in preferences if val in supported), None)
    if fallback:
        kon_logger.info(
            f"[STT] CTranslate2 compute_type '{compute_type}' não suportado em '{device}'; usando '{fallback}'."
        )
        return fallback
    return compute_type


class WhisperSTTEngine(BaseSTTEngine):
    """
    Decoupled faster-whisper STT implementation.
    Standardized on 'small' model with CPU int8 quantization and hardware fallback.
    """

    _instance_lock = threading.RLock()
    _shared_model = None

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        default_language: str = "pt",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = _resolve_compute_type(device, compute_type)
        self.default_language = default_language
        self._last_latency = 0.0

    def _get_model(self):
        if WhisperSTTEngine._shared_model is None:
            with WhisperSTTEngine._instance_lock:
                if WhisperSTTEngine._shared_model is None:
                    t0 = time.time()
                    kon_logger.info(
                        f"[STT] Carregando modelo faster-whisper '{self.model_size}' "
                        f"({self.device}/{self.compute_type})..."
                    )
                    from faster_whisper import WhisperModel
                    try:
                        WhisperSTTEngine._shared_model = WhisperModel(
                            self.model_size,
                            device=self.device,
                            compute_type=self.compute_type,
                            cpu_threads=4,
                            local_files_only=True,
                        )
                    except Exception:
                        WhisperSTTEngine._shared_model = WhisperModel(
                            self.model_size,
                            device=self.device,
                            compute_type=self.compute_type,
                            cpu_threads=4,
                        )
                    load_time = time.time() - t0
                    kon_logger.info(f"[STT] Modelo faster-whisper carregado em {load_time:.2f}s.")
        return WhisperSTTEngine._shared_model

    def preload(self) -> None:
        """
        Preloads faster-whisper model into memory and warms up execution graph.
        Called once during [BOOT] to prevent latency during user commands.
        """
        model = self._get_model()
        try:
            # Warm up CTranslate2 inference buffers with 0.1s dummy audio
            dummy_pcm = np.zeros(1600, dtype=np.float32)
            segments, _ = model.transcribe(dummy_pcm, language=self.default_language, beam_size=1, vad_filter=False)
            _ = list(segments)
        except Exception as exc:
            kon_logger.debug(f"[STT] Warmup concluído com aviso: {exc}")

    @property
    def last_latency(self) -> float:
        return self._last_latency

    def transcribe(self, audio: Union[np.ndarray, bytes, str], language: Optional[str] = None) -> str:
        """
        Transcribes 16kHz float32 or int16 audio array, bytes, or file path.
        """
        if isinstance(audio, np.ndarray) and len(audio) == 0:
            return ""

        if isinstance(audio, bytes) and len(audio) == 0:
            return ""

        lang = language or self.default_language
        kon_logger.info("[STT] Transcrevendo áudio...")
        t0 = time.time()

        try:
            model = self._get_model()

            # Handle numpy array format
            if isinstance(audio, np.ndarray):
                if audio.dtype != np.float32:
                    if audio.dtype == np.int16:
                        audio_data = audio.astype(np.float32) / 32768.0
                    else:
                        audio_data = audio.astype(np.float32)
                else:
                    audio_data = audio
            elif isinstance(audio, bytes):
                int16_arr = np.frombuffer(audio, dtype=np.int16)
                audio_data = int16_arr.astype(np.float32) / 32768.0
            else:
                audio_data = audio

            segments, info = model.transcribe(
                audio_data,
                language=lang,
                beam_size=1,                         # Greedy decoding for minimal latency and RAM/CPU usage
                vad_filter=False,                    # Audio already silence-trimmed by SimpleCommandCapture
                condition_on_previous_text=False,    # Avoid repeating hallucinated loops
            )

            parts = [s.text.strip() for s in segments]
            result_text = " ".join(parts).strip()
            self._last_latency = round(time.time() - t0, 2)
            kon_logger.info(f'[STT] Texto: "{result_text}" (latência: {self._last_latency}s)')
            return result_text

        except Exception as exc:
            self._last_latency = round(time.time() - t0, 2)
            kon_logger.error(f"[STT] Erro durante a transcrição: {exc}")
            return ""


class MockSTTEngine(BaseSTTEngine):
    """
    Mock STT for unit tests and automated continuous integration.
    """

    def __init__(self, default_text: str = "abrir navegador") -> None:
        self.default_text = default_text
        self._last_latency = 0.05

    @property
    def last_latency(self) -> float:
        return self._last_latency

    def transcribe(self, audio: Union[np.ndarray, bytes, str], language: str = "pt") -> str:
        self._last_latency = 0.01
        kon_logger.info(f'[STT] Transcrição MOCK: "{self.default_text}"')
        return self.default_text
