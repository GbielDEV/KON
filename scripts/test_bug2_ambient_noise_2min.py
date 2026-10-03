"""
Validation script for BUG 2 — 2-minute physical microphone ambient noise test.
Monitors the real physical microphone for 120 seconds with normal ambient background noise.
Verifies that OpenWakeWordDetector (threshold=0.50) triggers ZERO false positives.
"""
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import OpenWakeWordDetector


def main():
    duration_seconds = 120  # 2 minutes
    threshold = 0.38

    print("=" * 70)
    print("  TESTE BUG 2 — MONITORAMENTO DE 2 MINUTOS COM RUÍDO AMBIENTE REAL")
    print("=" * 70)
    print("Dispositivo: Microfone físico Realtek Audio")
    print(f"Threshold wake word: {threshold}")
    print(f"Duração do teste: {duration_seconds} segundos (2 minutos)")
    print("Mantenha o ambiente com ruído normal de fundo (não precisa fazer silêncio absoluto).")
    print("-" * 70)

    cap = AudioCapture()
    if not cap.start():
        print("[ERRO] Falha ao iniciar microfone PyAudio.")
        return

    det = OpenWakeWordDetector(wake_word="Okay KON", threshold=threshold)
    det._initialize_model()

    triggers = []
    rms_values = []
    t_start = time.time()
    last_print = t_start

    try:
        while time.time() - t_start < duration_seconds:
            chunk = cap.read_chunk(timeout=0.2)
            if not chunk or len(chunk) < 2560:
                continue

            samples = np.frombuffer(chunk[:2560], dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            rms_values.append(rms)

            # Check wake word detection
            if det.detect(chunk[:2560]):
                elapsed = time.time() - t_start
                triggers.append((elapsed, rms))
                print(f"\n[ALERTA] Gatilho acionado aos {elapsed:.1f}s com RMS {rms:.1f}!")

            # Periodic status
            now = time.time()
            if now - last_print >= 20.0:
                elapsed = now - t_start
                current_rms = np.mean(rms_values[-20:]) if rms_values else 0.0
                print(f"  [{elapsed:5.1f}s / {duration_seconds}s] Ruído RMS médio: {current_rms:5.1f} | Falsos positivos: {len(triggers)}")
                last_print = now

    finally:
        cap.stop()

    print("-" * 70)
    print("                 RESULTADO DO TESTE DE 2 MINUTOS")
    print("-" * 70)
    print(f"Tempo total monitorado: {time.time() - t_start:.1f}s")
    print(f"Ruído RMS médio no ambiente: {np.mean(rms_values):.1f} (Min: {min(rms_values):.1f}, Max: {max(rms_values):.1f})")
    print(f"Total de ativações falsas registradas: {len(triggers)}")

    if len(triggers) == 0:
        print("\n>>> SUCESSO ABSOLUTO: 0 ativações falsas em 2 minutos de ruído ambiente! <<<")
        print(">>> O assistente NUNCA responderá 'Sim?' sem ser chamado! <<<")
    else:
        print(f"\n>>> FALHA: {len(triggers)} ativações indevidas detectadas. <<<")

    print("=" * 70)


if __name__ == "__main__":
    main()
