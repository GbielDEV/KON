"""
Continuous Audio Capture subsystem for KON.
Standardized on PyAudio as the single, unified hardware audio capture driver.
Operates on a non-blocking background stream at 16000 Hz, 1 channel (mono), 16-bit PCM.
Supports clean pause/stop to release the microphone for SpeechRecognition without conflicts.
"""
from typing import Optional, Callable, List, Dict, Any, Tuple
import queue
import threading
import time

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False

from backend.core.logger import kon_logger


class AudioCapture:
    """
    Decoupled hardware audio capture using PyAudio.
    Standardized at 16000 Hz, 1 channel (mono), 16-bit PCM (int16).
    """

    SAMPLE_RATE = 16000
    CHANNELS = 1
    DTYPE = "int16"
    BLOCK_SIZE = 1280  # 80ms chunk (1280 samples / 2560 bytes)

    def __init__(self, device_index: Optional[int] = None) -> None:
        self.device_index = device_index
        self._pa: Optional[Any] = None
        self._stream: Optional[Any] = None
        self._queue: queue.Queue = queue.Queue(maxsize=500)
        self._listeners: List[Callable[[bytes], None]] = []
        self._lock = threading.Lock()
        self._is_running = False
        self.last_frame_received_at = 0.0

    def _get_pyaudio(self):
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError("PyAudio não está instalado no ambiente Python.")
        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        return self._pa

    def get_default_device_info(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves the default input device information using PyAudio.
        """
        try:
            pa = self._get_pyaudio()
            if self.device_index is not None and 0 <= self.device_index < pa.get_device_count():
                dev = pa.get_device_info_by_index(self.device_index)
                if dev.get("maxInputChannels", 0) > 0:
                    return dict(dev)

            try:
                default_info = pa.get_default_input_device_info()
                if default_info and default_info.get("maxInputChannels", 0) > 0:
                    return dict(default_info)
            except Exception:
                pass

            for idx in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(idx)
                if dev.get("maxInputChannels", 0) > 0:
                    return dict(dev)
        except Exception as exc:
            kon_logger.warning(f"[MIC] Falha ao consultar dispositivos de áudio via PyAudio: {exc}")
        return None

    def is_available(self) -> bool:
        dev = self.get_default_device_info()
        return dev is not None and dev.get("maxInputChannels", 0) > 0

    def get_device_name(self) -> str:
        dev = self.get_default_device_info()
        if dev:
            return dev.get("name", "Microfone Padrão (PyAudio)")
        return "Nenhum microfone detectado"

    def is_running(self) -> bool:
        return self._is_running

    def add_listener(self, callback: Callable[[bytes], None]) -> None:
        """Registers a callback to receive continuous raw PCM audio bytes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[bytes], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _pyaudio_callback(self, in_data, frame_count, time_info, status_flags):
        """
        PyAudio C-level streaming callback. Must execute quickly and never block.
        """
        t_arrival = time.time()
        self.last_frame_received_at = t_arrival
        raw_bytes = bytes(in_data)

        # Enqueue chunk with arrival timestamp for consumer loop
        try:
            self._queue.put_nowait((raw_bytes, t_arrival))
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((raw_bytes, t_arrival))
            except Exception:
                pass

        # Broadcast to frame listeners (VU meter, wake word detector, etc.)
        with self._lock:
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(raw_bytes)
            except Exception as exc:
                kon_logger.debug(f"[MIC] Erro em listener de áudio: {exc}")

        return (None, pyaudio.paContinue)

    def start(self) -> bool:
        """
        Starts the continuous PyAudio stream on a dedicated thread managed by PortAudio.
        """
        with self._lock:
            if self._is_running and self._stream is not None:
                return True

            dev = self.get_default_device_info()
            if not dev:
                kon_logger.error("[MIC] Não foi possível iniciar captura: microfone indisponível.")
                return False

            try:
                pa = self._get_pyaudio()
                device_idx = self.device_index if self.device_index is not None else dev.get("index")
                device_name = dev.get("name")
                kon_logger.info(
                    f"[MIC] Iniciando microfone via PyAudio: '{device_name}' (índice: {device_idx}) @ 16kHz mono"
                )

                self._stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=self.CHANNELS,
                    rate=self.SAMPLE_RATE,
                    input=True,
                    input_device_index=device_idx,
                    frames_per_buffer=self.BLOCK_SIZE,
                    stream_callback=self._pyaudio_callback,
                )
                self._stream.start_stream()
                self._is_running = True
                kon_logger.info("[MIC] Microfone PyAudio iniciado com sucesso. Captura contínua ativa.")
                return True
            except Exception as exc:
                kon_logger.error(f"[MIC] Falha ao iniciar stream PyAudio: {exc}")
                self._is_running = False
                return False

    def stop(self) -> None:
        """
        Stops and releases the audio input stream, completely freeing the microphone.
        """
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._is_running = False
            kon_logger.info("[MIC] Microfone PyAudio pausado/liberado.")

    def get_queue_size(self) -> int:
        """Returns the current number of pending chunks in the queue."""
        return self._queue.qsize()

    def read_chunk(self, timeout: float = 0.5) -> Optional[bytes]:
        """Reads next raw PCM chunk from the internal queue."""
        try:
            item = self._queue.get(timeout=timeout)
            if isinstance(item, tuple):
                raw_bytes, arrival_time = item
                self.last_chunk_arrival_time = arrival_time
                return raw_bytes
            return item
        except queue.Empty:
            return None

    def read_chunk_with_timestamp(self, timeout: float = 0.5) -> Tuple[Optional[bytes], float]:
        """Reads next raw PCM chunk and its arrival timestamp from the internal queue."""
        try:
            item = self._queue.get(timeout=timeout)
            if isinstance(item, tuple):
                return item
            return item, time.time()
        except queue.Empty:
            return None, 0.0

    def clear_queue(self) -> None:
        """Flushes the internal queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    # Backward compatibility aliases
    start_stream = start
    stop_stream = stop
    pause = stop
    resume = start
    is_streaming = is_running
    add_frame_listener = add_listener
    remove_frame_listener = remove_listener


# =========================================================================
# Legacy Sounddevice Implementation (Isolated, preserved for rollback)
# =========================================================================
class LegacySounddeviceAudioCapture:
    """Legacy sounddevice capture kept isolated for rollback."""
    SAMPLE_RATE = 16000
    CHANNELS = 1
    BLOCK_SIZE = 1280

    def __init__(self, device_index: Optional[int] = None) -> None:
        self.device_index = device_index
        self._stream = None

    def start(self) -> bool:
        kon_logger.warning("[MIC_LEGACY] Chamada para LegacySounddeviceAudioCapture desativada no fluxo principal.")
        return False

    def stop(self) -> None:
        pass
