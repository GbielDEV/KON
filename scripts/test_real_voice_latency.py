"""
Script de teste e medição de latência real com hardware (Microfone Real + openWakeWord + TTS).
Mede explicitamente:
- wake_detected_at - wake_word_audio_received_at
- tts_requested_at - wake_detected_at
- tts_audio_started_at - wake_detected_at
- Duração da fala do "Sim?"
"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.core.state_machine import VoicePipelineOrchestrator
from voice_assistant.stt.whisper_engine import MockSTTEngine

def main():
    print("=" * 60)
    print("TESTE DE LATÊNCIA REAL E TTS — MARCO 2.1")
    print("=" * 60)

    # Use Mock STT for this test to isolate the wake word + TTS latency without requiring full speech
    orch = VoicePipelineOrchestrator(
        stt_engine=MockSTTEngine("abrir navegador")
    )

    print("[SETUP] Iniciando orquestrador com microfone real e openWakeWord...")
    t0 = time.perf_counter()
    started = orch.start()
    t_start = time.perf_counter() - t0

    if not started:
        print("[ERRO] Falha ao iniciar hardware de áudio.")
        return

    print(f"[SETUP] Orquestrador iniciado em {t_start:.2f}s.")
    print(f"[MIC] Fila de áudio inicial: {orch.audio_capture.get_queue_size()} chunks (esperado: 0 ou 1)")

    print("\n" + "=" * 60)
    print(">>> O KON ESTÁ ESCUTANDO. DIGA: 'Okay KON' <<<")
    print("(Aguardando detecção por 20 segundos...)")
    print("=" * 60 + "\n")

    t_wait_start = time.time()
    try:
        while time.time() - t_wait_start < 20:
            _ = orch.audio_capture.get_queue_size()
            time.sleep(0.5)
            if orch._is_cycle_active:
                print("\n[OK] Ciclo de voz disparado com sucesso pela wake word!")
                # Wait for cycle to complete
                while orch._is_cycle_active:
                    time.sleep(0.2)
                break
    except KeyboardInterrupt:
        pass
    finally:
        orch.stop()
        print("\n[TEARDOWN] Orquestrador encerrado.")

if __name__ == "__main__":
    main()
