"""
Script de diagnóstico interativo em tempo real para Wake Word.
Mede o nível do microfone (VU meter) e os scores exatos de cada modelo openWakeWord.
Permite testar falar "Okay KON", "Jarvis", "Alexa", etc., e ver na tela o que o microfone ouve!
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import OpenWakeWordDetector

def main():
    print("=" * 60)
    print("  DIAGNÓSTICO INTERATIVO DE WAKE WORD E MICROFONE")
    print("=" * 60)

    detector = OpenWakeWordDetector(wake_word="Okay KON", threshold=0.15)
    detector._initialize_model()

    print(f"\n[WAKE] Modelos ativos no openWakeWord: {detector._active_models}")
    print("[WAKE] Threshold configurado:", detector.threshold)

    cap = AudioCapture()
    if not cap.start():
        print("[MIC] ERRO: Não foi possível iniciar o microfone.")
        return

    print(f"[MIC] Dispositivo conectado: {cap.get_device_name()}")
    print("\nFale no microfone agora: 'Okay KON', 'Jarvis', 'Alexa'...")
    print("Pressione Ctrl+C para parar.\n")
    print("-" * 60)

    try:
        count = 0
        while True:
            chunk = cap.read_chunk(timeout=0.2)
            if chunk is None or len(chunk) < 2560:
                continue

            # Calculate audio volume (RMS)
            samples = np.frombuffer(chunk, dtype=np.int16)
            rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
            # Level bar (0 to 30 chars)
            level_bars = int(min(30, rms / 150))
            vu_bar = "#" * level_bars + " " * (30 - level_bars)

            # Predict openwakeword scores
            scores = detector._model.predict(samples[:1280])

            # Format scores
            score_strs = []
            for name, sc in scores.items():
                short_name = name.replace("_v0.1", "")
                score_strs.append(f"{short_name}:{sc:.2f}")

            count += 1
            if count % 2 == 0:  # Print every ~160ms
                sys.stdout.write(f"\rVol: [{vu_bar}] (RMS:{int(rms):4d}) | {' '.join(score_strs)}")
                sys.stdout.flush()

            # Check if any model crossed threshold
            for name, sc in scores.items():
                if sc >= 0.25:
                    print(f"\n>>> [GATILHO DETECTADO!] Modelo: '{name}' com Score: {sc:.3f} <<<")

    except KeyboardInterrupt:
        print("\n\nEncerrando teste...")
    finally:
        cap.stop()

if __name__ == "__main__":
    main()
