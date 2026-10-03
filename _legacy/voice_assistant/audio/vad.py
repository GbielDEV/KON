"""
Voice Activity Detection (VAD) using webrtcvad.
Accurately detects start of speech, speech continuity, and silence.
Silence timeout defaults to 1.5s (configurable).

Flow:
  WAITING_FOR_SPEECH
  → SPEECH_STARTED        (>= 3 speech subframes in an 80ms chunk)
  → CONTINUE_SPEECH / SILENCE_STARTED  (silence timer starts only here)
  → after silence_timeout consecutive seconds of silence
  → END_CAPTURE
"""
from typing import Optional, List
import time
import webrtcvad
import numpy as np
from backend.core.logger import kon_logger
from voice_assistant.audio.capture import AudioCapture


class VoiceActivityDetector:
    """
    WebRTC VAD wrapper for 16kHz mono 16-bit PCM audio.
    Slices raw audio into valid 20ms frames (320 samples, 640 bytes) and tracks speech state.
    """

    SAMPLE_RATE = 16000
    FRAME_MS = 20           # 20ms frame
    FRAME_SAMPLES = int(SAMPLE_RATE * (FRAME_MS / 1000.0))   # 320 samples
    FRAME_BYTES = FRAME_SAMPLES * 2                           # 640 bytes for 16-bit PCM

    # A chunk of 80ms has 4 sub-frames.
    # Require >= 3 sub-frames of real speech (60ms out of 80ms) to classify chunk as speech.
    # This prevents ambient noise (1-2 stray frames) from resetting the silence timer.
    SPEECH_SUBFRAME_THRESHOLD = 3

    def __init__(self, mode: int = 2, default_silence_timeout: float = 1.5) -> None:
        """
        :param mode: webrtcvad aggressiveness level (0 to 3). 2 is balanced, 3 is most aggressive.
        :param default_silence_timeout: Seconds of consecutive silence after speech to mark end
                                        of phrase (default 1.5s). Timer starts ONLY after speech
                                        onset has been confirmed.
        """
        self.vad = webrtcvad.Vad(mode)
        self.default_silence_timeout = default_silence_timeout

    def is_speech_frame(self, frame_bytes: bytes) -> bool:
        """
        Evaluates a single 20ms (640 bytes) PCM frame.
        """
        if len(frame_bytes) != self.FRAME_BYTES:
            return False
        try:
            return self.vad.is_speech(frame_bytes, self.SAMPLE_RATE)
        except Exception as exc:
            kon_logger.debug(f"[VAD] Erro na verificação do frame: {exc}")
            return False

    def is_speech(self, audio_bytes: bytes) -> bool:
        """
        Evaluates arbitrary audio chunk by slicing into 20ms frames and voting.
        """
        if len(audio_bytes) < self.FRAME_BYTES:
            return False

        votes = 0
        total = 0
        for i in range(0, len(audio_bytes) - self.FRAME_BYTES + 1, self.FRAME_BYTES):
            chunk = audio_bytes[i:i + self.FRAME_BYTES]
            if self.is_speech_frame(chunk):
                votes += 1
            total += 1

        return total > 0 and (votes / total) >= 0.5

    def _count_speech_subframes(self, chunk: bytes) -> int:
        """
        Returns the number of 20ms sub-frames classified as speech within an 80ms chunk.
        """
        count = 0
        for i in range(0, len(chunk) - self.FRAME_BYTES + 1, self.FRAME_BYTES):
            sub_frame = chunk[i:i + self.FRAME_BYTES]
            if self.is_speech_frame(sub_frame):
                count += 1
        return count

    def capture_command(
        self,
        audio_capture: AudioCapture,
        max_duration: float = 8.0,
        silence_timeout: Optional[float] = None,
        initial_timeout: float = 4.0,
    ) -> np.ndarray:
        """
        Listens to continuous audio stream and captures user phrase until silence_timeout
        seconds of consecutive silence AFTER speech onset (default 1.5s).

        State machine:
          WAITING_FOR_SPEECH → SPEECH_STARTED → [CONTINUE_SPEECH | SILENCE_STARTED] → END_CAPTURE

        Silence timer is ONLY started after speech_started == True.
        Returns normalized float32 numpy array ready for faster-whisper.
        """
        silence_limit = silence_timeout if silence_timeout is not None else self.default_silence_timeout
        kon_logger.info(f"[VAD] Aguardando fala do comando (silêncio configurado: {silence_limit}s)...")

        audio_capture.clear_queue()
        pre_roll_chunks: List[bytes] = []
        recorded_chunks: List[bytes] = []

        # --- State ---
        speech_started = False                  # WAITING_FOR_SPEECH until first solid speech chunk
        silence_start_time: Optional[float] = None  # SILENCE_STARTED timer (None = not in silence)
        # -------------

        start_time = time.time()
        last_speech_log_time = 0.0

        while True:
            chunk = audio_capture.read_chunk(timeout=0.1)
            now = time.time()

            # Absolute maximum capture guard
            if now - start_time >= max_duration:
                kon_logger.info(f"[VAD] Tempo máximo de captura atingido ({max_duration}s).")
                break

            # No chunk or too small — only relevant after speech started
            if chunk is None or len(chunk) < self.FRAME_BYTES:
                if speech_started and silence_start_time is not None:
                    elapsed_silence = now - silence_start_time
                    if elapsed_silence >= silence_limit:
                        kon_logger.info(
                            f"[VAD] {silence_limit:.1f}s de silêncio consecutivo (sem chunk). "
                            f"Encerrando captura."
                        )
                        break
                continue

            # Count how many 20ms sub-frames within this 80ms chunk contain speech
            speech_subframes = self._count_speech_subframes(chunk)
            # A chunk is considered "solid speech" only if >= SPEECH_SUBFRAME_THRESHOLD subframes
            # are speech (default: 3 out of 4, i.e., 60ms of 80ms).
            # This rejects ambient noise that would otherwise reset the silence timer.
            has_solid_speech = (speech_subframes >= self.SPEECH_SUBFRAME_THRESHOLD)

            if not speech_started:
                # ── PHASE 1: WAITING_FOR_SPEECH ──────────────────────────────────────
                # Maintain a short pre-roll ring buffer (~240ms = 3 chunks of 80ms)
                # so initial phonemes / consonants are not lost.
                pre_roll_chunks.append(chunk)
                if len(pre_roll_chunks) > 3:
                    pre_roll_chunks.pop(0)

                if has_solid_speech:
                    # Transition to SPEECH_STARTED
                    speech_started = True
                    silence_start_time = None   # Silence timer does NOT run yet
                    recorded_chunks.extend(pre_roll_chunks)
                    kon_logger.info(
                        f"[VAD] Início da fala detectado "
                        f"({speech_subframes}/4 sub-frames @ {(now - start_time):.2f}s)"
                    )
                    last_speech_log_time = now

                elif now - start_time >= initial_timeout:
                    kon_logger.info(
                        f"[VAD] Nenhuma fala detectada no tempo inicial ({initial_timeout:.1f}s)."
                    )
                    break

            else:
                # ── PHASE 2: SPEECH_STARTED — track speech vs. silence ───────────────
                recorded_chunks.append(chunk)

                if has_solid_speech:
                    # ── CONTINUE_SPEECH ──────────────────────────────────────────────
                    if silence_start_time is not None:
                        # Genuine speech resumed after a pause — reset silence timer
                        elapsed_silence = now - silence_start_time
                        kon_logger.info(
                            f"[VAD] Fala retomada após {elapsed_silence:.2f}s de pausa "
                            f"({speech_subframes}/4 sub-frames)"
                        )
                        silence_start_time = None
                    elif now - last_speech_log_time >= 1.2:
                        kon_logger.info(
                            f"[VAD] Fala continua ({speech_subframes}/4 sub-frames)"
                        )
                        last_speech_log_time = now

                else:
                    # ── SILENCE_STARTED / SILENCE_CONTINUING ──────────────────────────
                    if silence_start_time is None:
                        # Start the silence timer
                        silence_start_time = now
                        kon_logger.info(
                            f"[VAD] Silêncio detectado ({speech_subframes}/4 sub-frames). "
                            f"Contagem regressiva: {silence_limit:.1f}s..."
                        )

                    elapsed_silence = now - silence_start_time
                    if elapsed_silence >= silence_limit:
                        kon_logger.info(
                            f"[VAD] {silence_limit:.1f}s de silêncio consecutivo atingidos "
                            f"({elapsed_silence:.2f}s). Encerrando captura."
                        )
                        break

        if not recorded_chunks or not speech_started:
            return np.zeros(0, dtype=np.float32)

        # Trim trailing silence: keep up to 300ms of trailing silence for natural phrasing
        # Each chunk is 80ms. Drop chunks beyond 300ms (~4 chunks) of trailing silence.
        silence_trail_chunks = max(0, int((silence_limit - 0.3) / 0.08))
        if silence_trail_chunks > 0 and len(recorded_chunks) > silence_trail_chunks + 3:
            final_chunks = recorded_chunks[:-silence_trail_chunks]
        else:
            final_chunks = recorded_chunks

        combined = b"".join(final_chunks)
        int16_audio = np.frombuffer(combined, dtype=np.int16)
        float_audio = int16_audio.astype(np.float32) / 32768.0
        duration = len(float_audio) / self.SAMPLE_RATE
        kon_logger.info(f"[VAD] Gravação concluída: {duration:.2f}s capturados.")
        return float_audio
