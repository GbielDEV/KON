"""
Text-to-Speech (TTS) subsystem using pyttsx3.
Non-blocking execution through a dedicated background worker queue.
Captures remain isolated and run concurrently while speech is being synthesized.
Configured for Brazilian Portuguese (Microsoft Maria / Windows pt-BR).
"""
from typing import Optional, Callable
import threading
import queue
import time
import pyttsx3
from backend.core.logger import kon_logger


class TextToSpeech:
    """
    Thread-safe TTS engine using pyttsx3 and Windows SAPI5.
    """

    _worker_thread: Optional[threading.Thread] = None
    _queue: queue.Queue = queue.Queue()
    _lock = threading.Lock()
    _is_speaking = False
    _last_latency = 0.0

    def __init__(self) -> None:
        self._ensure_worker_running()

    @classmethod
    def _ensure_worker_running(cls) -> None:
        with cls._lock:
            if cls._worker_thread is None or not cls._worker_thread.is_alive():
                cls._worker_thread = threading.Thread(
                    target=cls._speech_loop,
                    name="KON-VoiceAssistant-TTS",
                    daemon=True,
                )
                cls._worker_thread.start()

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def preload(self) -> None:
        """Ensures worker thread is running and SAPI5 COM engine is initialized."""
        self._ensure_worker_running()

    @property
    def last_latency(self) -> float:
        return self._last_latency

    @classmethod
    def _speech_loop(cls) -> None:
        """
        Background worker thread: Initializes COM apartment and executes speech tasks.
        """
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

        # Probe available voices once
        pt_voice_id = None
        pt_voice_name = None
        try:
            probe = pyttsx3.init("sapi5")
            for v in probe.getProperty("voices"):
                v_name = v.name.lower()
                v_id = v.id.lower()
                if "maria" in v_name or "brazil" in v_name or "portuguese" in v_name or "pt-br" in v_id:
                    pt_voice_id = v.id
                    pt_voice_name = v.name
                    break
            del probe
            kon_logger.info("[TTS] inicializado")
            if pt_voice_id:
                kon_logger.info(f"[TTS] Voz selecionada: {pt_voice_name or 'Microsoft Maria'}")
                kon_logger.info("[TTS] Idioma: pt-BR")
            else:
                kon_logger.info("[TTS] Utilizando voz padrão do Windows.")
        except Exception as exc:
            kon_logger.error(f"[TTS] Erro ao detectar vozes SAPI5: {exc}")

        while True:
            try:
                item = cls._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            if len(item) == 3:
                text, on_complete, on_start = item
            else:
                text, on_complete = item
                on_start = None

            cls._is_speaking = True
            t0 = time.time()
            now_str = time.strftime("%H:%M:%S") + f".{int((t0 % 1) * 1000):03d}"
            kon_logger.info(f'[{now_str}] [TTS] worker iniciou: "{text}"')

            try:
                engine = pyttsx3.init("sapi5")
                engine.setProperty("rate", 180)
                if pt_voice_id:
                    engine.setProperty("voice", pt_voice_id)

                if on_start and callable(on_start):
                    try:
                        on_start()
                    except Exception as start_err:
                        kon_logger.debug(f"[TTS] Erro no callback on_start: {start_err}")

                t_audio_start = time.time()
                now_str = time.strftime("%H:%M:%S") + f".{int((t_audio_start % 1) * 1000):03d}"
                kon_logger.info(f'[{now_str}] [TTS] áudio começou: "{text}"')

                engine.say(text)
                engine.runAndWait()
                del engine
            except Exception as exc:
                kon_logger.error(f"[TTS] Falha ao sintetizar voz: {exc}")
            finally:
                t_end = time.time()
                now_str = time.strftime("%H:%M:%S") + f".{int((t_end % 1) * 1000):03d}"
                kon_logger.info(f'[{now_str}] [TTS] áudio finalizado ({t_end - t0:.2f}s)')
                cls._last_latency = round(t_end - t0, 2)
                cls._is_speaking = False

                if on_complete and callable(on_complete):
                    try:
                        on_complete()
                    except Exception as cb_err:
                        kon_logger.error(f"[TTS] Erro no callback de conclusão: {cb_err}")

                cls._queue.task_done()

    def falar(
        self,
        texto: str,
        on_complete: Optional[Callable[[], None]] = None,
        on_start: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Enqueues text for speech synthesis without blocking the caller.
        """
        if not texto or not texto.strip():
            return
        self._ensure_worker_running()
        self._queue.put((texto.strip(), on_complete, on_start))

    speak = falar

    def stop(self) -> None:
        pass


# Global singleton instance
_GLOBAL_TTS = TextToSpeech()


def falar(
    texto: str,
    on_complete: Optional[Callable[[], None]] = None,
    on_start: Optional[Callable[[], None]] = None,
) -> None:
    """
    Convenience function for non-blocking speech synthesis.
    """
    _GLOBAL_TTS.falar(texto, on_complete=on_complete, on_start=on_start)
