"""
Simple Audio Capture Subsystem for KON Command Recording.
Uses PyAudio to record audio commands after wake word activation in a simple,
predictable, and deterministic manner without complex multi-state VAD machines.

Standard parameters:
- Format: 16-bit PCM (int16)
- Sample Rate: 16000 Hz
- Channels: 1 (Mono)
- Chunk Size: 1024 frames (~64ms per chunk)
"""
from typing import Optional, List, Any
import time
import numpy as np

from backend.core.logger import kon_logger

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False


class SimpleCommandCapture:
    """
    Simple and deterministic audio capture module for user voice commands.
    Directly streams from the microphone using PyAudio (16kHz, 16-bit mono, CHUNK=1024).
    Replaces complex webrtcvad state machines with a simple energy/RMS threshold
    and safety timeout.
    """

    RATE = 16000
    CHANNELS = 1
    CHUNK = 1024
    FORMAT_INT16 = 2  # pyaudio.paInt16 is 2

    def __init__(
        self,
        rate: int = RATE,
        channels: int = CHANNELS,
        chunk: int = CHUNK,
        default_silence_threshold: float = 400.0,
        default_silence_duration: float = 1.0,
        default_max_duration: float = 4.0,
        device_index: Optional[int] = None,
    ) -> None:
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self.default_silence_threshold = default_silence_threshold
        self.default_silence_duration = default_silence_duration
        self.default_max_duration = default_max_duration
        self.device_index = device_index
        self._pa: Optional[Any] = None

    def _get_pyaudio(self):
        """Lazily initializes and reuses PyAudio instance."""
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError(
                "PyAudio não está instalado no ambiente. Execute: pip install pyaudio"
            )
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        return self._pa

    def is_available(self) -> bool:
        """Returns True if PyAudio is installed and an input device is accessible."""
        if not PYAUDIO_AVAILABLE:
            return False
        try:
            pa = self._get_pyaudio()
            count = pa.get_device_count()
            return count > 0
        except Exception:
            return False

    def get_device_name(self) -> str:
        """Returns the name of the default input audio device."""
        try:
            pa = self._get_pyaudio()
            default_info = pa.get_default_input_device_info()
            return default_info.get("name", "Microfone Padrão (PyAudio)")
        except Exception as exc:
            kon_logger.warning(f"[CAPTURE] Falha ao obter nome do dispositivo: {exc}")
            return "Microfone Padrão"

    def compute_rms(self, raw_bytes: bytes) -> float:
        """Calculates root-mean-square (RMS) amplitude of 16-bit PCM bytes."""
        if len(raw_bytes) < 2:
            return 0.0
        samples = np.frombuffer(raw_bytes, dtype=np.int16)
        return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))

    def capture_command(
        self,
        max_duration: Optional[float] = None,
        silence_threshold: Optional[float] = None,
        silence_duration: Optional[float] = None,
        min_duration: float = 1.0,
        startup_timeout: float = 3.5,
    ) -> np.ndarray:
        """
        Captures a single voice command from the microphone.

        Deterministic flow:
          1. Opens 16kHz mono 16-bit PCM stream.
          2. Continuously reads CHUNK=1024 frames into a buffer.
          3. Evaluates simple RMS energy.
          4. When speech is detected (RMS >= silence_threshold), starts watching for silence.
          5. Concludes when silence_duration is reached after speech, or max_duration is reached.
          6. Returns float32 numpy array ready for faster-whisper.
        """
        max_sec = max_duration if max_duration is not None else self.default_max_duration
        threshold = silence_threshold if silence_threshold is not None else self.default_silence_threshold
        silence_sec = silence_duration if silence_duration is not None else self.default_silence_duration

        chunk_duration = self.chunk / float(self.rate)  # 1024 / 16000 = 0.064s (64ms)
        silence_chunks_needed = max(1, int(silence_sec / chunk_duration))

        kon_logger.info(
            f"[CAPTURE] Iniciando gravação de comando (max: {max_sec:.1f}s, "
            f"limiar silêncio: {threshold:.0f}, silêncio fim: {silence_sec:.1f}s)..."
        )

        frames: List[bytes] = []
        speech_started = False
        consecutive_silence = 0
        peak_rms = 0.0

        stream = None
        start_time = time.time()

        try:
            pa = self._get_pyaudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk,
            )

            while True:
                data = stream.read(self.chunk, exception_on_overflow=False)
                frames.append(data)

                now = time.time()
                elapsed = now - start_time

                rms = self.compute_rms(data)
                if rms > peak_rms:
                    peak_rms = rms

                if rms >= threshold:
                    if not speech_started:
                        speech_started = True
                        kon_logger.info(
                            f"[CAPTURE] Fala detectada (RMS: {rms:.1f} >= {threshold:.0f} @ {elapsed:.2f}s)"
                        )
                    consecutive_silence = 0
                else:
                    if speech_started:
                        consecutive_silence += 1
                        if elapsed >= min_duration and consecutive_silence >= silence_chunks_needed:
                            kon_logger.info(
                                f"[CAPTURE] Término da fala detectado ({consecutive_silence * chunk_duration:.2f}s silêncio @ {elapsed:.2f}s)."
                            )
                            break
                    else:
                        # User hasn't started talking yet
                        if elapsed >= startup_timeout:
                            kon_logger.info(
                                f"[CAPTURE] Nenhuma fala detectada no tempo inicial ({startup_timeout:.1f}s)."
                            )
                            break

                if elapsed >= max_sec:
                    kon_logger.info(f"[CAPTURE] Limite máximo de gravação atingido ({max_sec:.1f}s).")
                    break

        except Exception as exc:
            kon_logger.error(f"[CAPTURE] Erro na captura de áudio com PyAudio: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass

        if not frames:
            kon_logger.warning("[CAPTURE] Nenhum frame de áudio gravado.")
            return np.zeros(0, dtype=np.float32)

        # Convert recorded 16-bit PCM bytes to float32 numpy array for faster-whisper
        raw_pcm = b"".join(frames)
        int16_samples = np.frombuffer(raw_pcm, dtype=np.int16)
        float_samples = int16_samples.astype(np.float32) / 32768.0
        duration = len(float_samples) / float(self.rate)

        kon_logger.info(
            f"[CAPTURE] Gravação finalizada: {duration:.2f}s ({len(frames)} chunks, pico RMS: {peak_rms:.1f})."
        )
        return float_samples

    def close(self) -> None:
        """Terminates PyAudio instance."""
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
