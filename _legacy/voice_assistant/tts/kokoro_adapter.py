"""
Kokoro TTS Adapter — Optional neural voice synthesis for KON.
Adapted from OpenJarvis (Apache-2.0 License).
Copyright 2026 OpenJarvis Contributors / Stanford SAIL. Adapted for KON Assistant.

Provides high-quality neural TTS using Kokoro v1.x as an OPTIONAL alternative
to the default Windows SAPI5 (pyttsx3) engine. Falls back gracefully if
the kokoro package is not installed.

Usage:
    This adapter is designed to be used alongside the existing TextToSpeech class.
    Set TTS_ENGINE=kokoro in .env or call KokoroTTSAdapter directly.
"""
from __future__ import annotations

import io
import threading
import time
import queue
from typing import Optional, Callable, Any, Dict
from collections import OrderedDict

from backend.core.logger import kon_logger


# Kokoro voice-prefix → lang_code mapping (from OpenJarvis)
_VOICE_PREFIX_TO_LANG: Dict[str, str] = {
    "a": "a",  # American English
    "b": "b",  # British English
    "z": "z",  # Mandarin Chinese
    "j": "j",  # Japanese
    "f": "f",  # French
    "i": "i",  # Italian
    "p": "p",  # Brazilian Portuguese
    "h": "h",  # Hindi
    "e": "e",  # Spanish
}

_DEFAULT_LANG_CODE = "p"  # Portuguese (Brazil) — KON default
_DEFAULT_VOICE_ID = "pf_dora"  # Portuguese female voice

# Sentinel to detect if kokoro is available
_KOKORO_AVAILABLE: Optional[bool] = None


def _check_kokoro_available() -> bool:
    """Lazy-check if kokoro package is installed."""
    global _KOKORO_AVAILABLE
    if _KOKORO_AVAILABLE is None:
        try:
            import kokoro  # noqa: F401
            _KOKORO_AVAILABLE = True
            kon_logger.info("[TTS-KOKORO] Kokoro TTS v1.x detectado e disponível.")
        except ImportError:
            _KOKORO_AVAILABLE = False
            kon_logger.info("[TTS-KOKORO] Kokoro TTS não instalado. Use 'pip install kokoro' para habilitar.")
    return _KOKORO_AVAILABLE


class KokoroTTSAdapter:
    """
    Thread-safe Kokoro TTS adapter with background worker queue.
    Mirrors the TextToSpeech API from speak.py for drop-in compatibility.

    Features (adapted from OpenJarvis):
    - Lazy pipeline creation per language code
    - LRU cache of pipelines (max 2 for 8 GB RAM machines)
    - Thread-safe inference with RLock
    - Non-blocking queue-based synthesis
    """

    _worker_thread: Optional[threading.Thread] = None
    _queue: queue.Queue = queue.Queue()
    _lock = threading.Lock()
    _is_speaking = False
    _last_latency = 0.0

    def __init__(
        self,
        voice_id: str = _DEFAULT_VOICE_ID,
        device: str = "cpu",
        max_cached_pipelines: int = 2,
    ) -> None:
        self.voice_id = voice_id
        self.device = device
        self.max_cached_pipelines = max_cached_pipelines
        self._model: Any = None
        self._pipelines: OrderedDict[str, Any] = OrderedDict()
        self._pipeline_lock = threading.RLock()
        self._available = _check_kokoro_available()

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def last_latency(self) -> float:
        return self._last_latency

    @staticmethod
    def _lang_for_voice(voice_id: str) -> str:
        """Return the Kokoro lang_code for a voice ID."""
        if not voice_id:
            return _DEFAULT_LANG_CODE
        return _VOICE_PREFIX_TO_LANG.get(voice_id[:1], _DEFAULT_LANG_CODE)

    def _get_pipeline(self, lang_code: str) -> Any:
        """
        Returns a KPipeline for the given language code, creating one if needed.
        Evicts the least-recently-used pipeline if the cache is full.
        """
        with self._pipeline_lock:
            if lang_code in self._pipelines:
                self._pipelines.move_to_end(lang_code)
                return self._pipelines[lang_code]

            from kokoro import KPipeline
            pipeline = KPipeline(lang_code=lang_code, device=self.device)
            self._pipelines[lang_code] = pipeline

            # Evict LRU if over limit
            while len(self._pipelines) > self.max_cached_pipelines:
                evicted_key, _ = self._pipelines.popitem(last=False)
                kon_logger.debug(f"[TTS-KOKORO] Pipeline evitado do cache: lang='{evicted_key}'")

            return pipeline

    def _synthesize_audio(self, text: str) -> Optional[bytes]:
        """
        Synthesizes text into WAV audio bytes using Kokoro.
        Returns None on failure.
        """
        if not self._available:
            return None

        try:
            lang_code = self._lang_for_voice(self.voice_id)
            pipeline = self._get_pipeline(lang_code)

            with self._pipeline_lock:
                # Kokoro returns generator of audio segments
                audio_segments = list(pipeline(text, voice=self.voice_id))

            if not audio_segments:
                return None

            import numpy as np
            import soundfile as sf

            # Concatenate all audio segments
            all_audio = np.concatenate([seg.audio for seg in audio_segments if seg.audio is not None])

            # Convert to WAV bytes
            buf = io.BytesIO()
            sf.write(buf, all_audio, samplerate=24000, format="WAV")
            return buf.getvalue()

        except Exception as exc:
            kon_logger.error(f"[TTS-KOKORO] Erro na síntese: {exc}")
            return None

    def preload(self) -> None:
        """Pre-loads the pipeline for the default language."""
        if self._available:
            try:
                lang_code = self._lang_for_voice(self.voice_id)
                self._get_pipeline(lang_code)
                kon_logger.info(f"[TTS-KOKORO] Pipeline pré-carregado para lang='{lang_code}'")
            except Exception as exc:
                kon_logger.error(f"[TTS-KOKORO] Erro no preload: {exc}")

    @classmethod
    def _ensure_worker_running(cls) -> None:
        with cls._lock:
            if cls._worker_thread is None or not cls._worker_thread.is_alive():
                cls._worker_thread = threading.Thread(
                    target=cls._speech_loop,
                    name="KON-VoiceAssistant-TTS-Kokoro",
                    daemon=True,
                )
                cls._worker_thread.start()

    @classmethod
    def _speech_loop(cls) -> None:
        """Background worker thread for Kokoro TTS."""
        import sounddevice as sd

        while True:
            try:
                item = cls._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            adapter, text, on_complete, on_start = item
            cls._is_speaking = True
            t0 = time.time()

            try:
                if on_start and callable(on_start):
                    on_start()

                wav_bytes = adapter._synthesize_audio(text)
                if wav_bytes:
                    import soundfile as sf

                    buf = io.BytesIO(wav_bytes)
                    data, samplerate = sf.read(buf)
                    kon_logger.info(f'[TTS-KOKORO] Reproduzindo: "{text}"')
                    sd.play(data, samplerate)
                    sd.wait()
                else:
                    kon_logger.warning("[TTS-KOKORO] Síntese retornou vazio, pulando reprodução.")

            except Exception as exc:
                kon_logger.error(f"[TTS-KOKORO] Erro na reprodução: {exc}")
            finally:
                t_end = time.time()
                cls._last_latency = round(t_end - t0, 2)
                cls._is_speaking = False
                kon_logger.info(f"[TTS-KOKORO] Concluído em {cls._last_latency}s")

                if on_complete and callable(on_complete):
                    try:
                        on_complete()
                    except Exception as cb_err:
                        kon_logger.error(f"[TTS-KOKORO] Erro no callback: {cb_err}")

                cls._queue.task_done()

    def falar(
        self,
        texto: str,
        on_complete: Optional[Callable[[], None]] = None,
        on_start: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Enqueues text for Kokoro neural speech synthesis.
        API-compatible with TextToSpeech.falar().
        """
        if not texto or not texto.strip():
            return
        if not self._available:
            kon_logger.warning("[TTS-KOKORO] Kokoro não disponível. Texto descartado.")
            return

        self._ensure_worker_running()
        self._queue.put((self, texto.strip(), on_complete, on_start))

    speak = falar

    def stop(self) -> None:
        pass
