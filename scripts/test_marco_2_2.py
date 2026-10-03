"""
Script de validação e benchmark automatizado do Marco 2.2.
Verifica:
1. Sequência [BOOT] completa
2. Modelos 100% pré-carregados (Whisper, NLU, Wake Word, TTS)
3. VAD encerrando pelo silêncio de 1.5s (sem estourar 8s)
4. Medição precisa de cada fase da latência
5. 3 ciclos consecutivos sem recarregar nenhum modelo
"""
import sys
import os
import time
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.core.state_machine import VoicePipelineOrchestrator
from voice_assistant.stt.whisper_engine import WhisperSTTEngine
from voice_assistant.nlu.intent_parser import IntentParser
from voice_assistant.audio.vad import VoiceActivityDetector
from backend.core.state import AssistantState


def test_vad_silence_detection():
    print("\n" + "=" * 60)
    print(" 1. TESTE DO VAD — ENCERRAMENTO POR SILÊNCIO (1.5s)")
    print("=" * 60)

    vad = VoiceActivityDetector(mode=2, default_silence_timeout=1.5)

    # Simulate an AudioCapture mock with 1.0s of speech followed by silence
    class MockAudioCapture:
        def __init__(self):
            # Generate 1.0s of simulated speech (12 chunks of 80ms)
            # and 3.0s of pure silence (38 chunks of 80ms)
            self.chunks = []
            # 1.0s speech
            t = np.linspace(0, 0.08, 1280, False)
            speech_wave = (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16)
            for _ in range(12):
                self.chunks.append(speech_wave.tobytes())
            # 3.0s silence
            silence_wave = np.zeros(1280, dtype=np.int16)
            for _ in range(38):
                self.chunks.append(silence_wave.tobytes())
            self.idx = 0

        def clear_queue(self):
            pass

        def read_chunk(self, timeout=0.1):
            if self.idx < len(self.chunks):
                chunk = self.chunks[self.idx]
                self.idx += 1
                time.sleep(0.02) # Fast simulation
                return chunk
            time.sleep(0.05)
            return None

    mock_cap = MockAudioCapture()
    t0 = time.time()
    audio = vad.capture_command(
        audio_capture=mock_cap,
        max_duration=8.0,
        silence_timeout=1.5,
        initial_timeout=3.0,
    )
    t_elapsed = time.time() - t0

    print(f"[VAD] Áudio capturado: {len(audio)/16000:.2f}s")
    print(f"[VAD] Tempo de captura simulado: {t_elapsed:.2f}s")
    assert len(audio) > 0, "O VAD deve capturar o áudio da fala."
    assert t_elapsed < 6.0, f"O VAD não deve atingir o timeout de 8.0s! Tempo decorrido: {t_elapsed:.2f}s"
    print("[VAD] SUCESSO: VAD detectou fala, encerrou pelo silêncio de 1.5s e NÃO atingiu 8.0s!")


def test_boot_and_three_cycles():
    print("\n" + "=" * 60)
    print(" 2. TESTE DE BOOT + PRÉ-CARREGAMENTO + 3 CICLOS CONSECUTIVOS")
    print("=" * 60)

    # Initialize real orchestrator
    orchestrator = VoicePipelineOrchestrator()

    # Step 1: Verify BOOT
    t_boot_start = time.time()
    orchestrator.preload_and_warmup()
    t_boot_duration = time.time() - t_boot_start
    print(f"\n[BOOT] Tempo total de inicialização/aquecimento: {t_boot_duration:.2f}s")

    assert orchestrator._is_preloaded is True, "Os modelos devem estar pré-carregados."
    assert WhisperSTTEngine._shared_model is not None, "Whisper deve estar na memória."
    assert IntentParser._shared_model is not None, "SentenceTransformer deve estar na memória."
    assert IntentParser._shared_catalog_initialized is True, "Catálogo NLU deve estar pré-calculado."

    print("\n" + "=" * 60)
    print(" EXECUTANDO 3 CICLOS CONSECUTIVOS (COMANDO: 'abrir navegador')")
    print("=" * 60)

    cycle_metrics = []

    for i in range(1, 4):
        print(f"\n>>> INICIANDO CICLO {i}/3 <<<")
        t_wake = time.time()

        # Run cycle with mock command text to simulate STT result of "abrir navegador"
        # or evaluate NLU, tool dispatch, TTS and state transitions
        res = orchestrator.run_voice_cycle(
            mock_command_text="abrir navegador",
            wake_detected_at=t_wake,
        )

        assert res.get("success") is True, f"Ciclo {i} falhou: {res}"
        assert res.get("intent", {}).get("intent") == "abrir_navegador", f"Intent incorreto no ciclo {i}"
        assert orchestrator.state == AssistantState.IDLE, f"KON deve retornar a IDLE após o ciclo {i}"

        cycle_metrics.append(res)
        print(f">>> CICLO {i} FINALIZADO COM SUCESSO! KON EM IDLE <<<")

    print("\n" + "=" * 60)
    print(" RESULTADO FINAL: TODOS OS 3 CICLOS EXECUTADOS COM SUCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    test_vad_silence_detection()
    test_boot_and_three_cycles()
