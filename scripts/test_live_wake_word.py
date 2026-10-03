"""
Live wake word validation test — NO KEYBOARD FALLBACK.
Measures 10 real live voice attempts spoken by the user to verify the revised acceptance criteria (>= 8 / 10).
"""
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import OpenWakeWordDetector


def main():
    threshold = 0.38
    total_rounds = 10
    round_duration = 4.0

    print("=" * 80)
    print("      TESTE DE VALIDAÇÃO AO VIVO — WAKE WORD 'Okay KON' (SEM TECLADO)")
    print("=" * 80)
    print("Critério de Aceite: Pelo menos 8 de 10 tentativas devem ativar o assistente")
    print("apenas pela voz, sem uso de gatilho manual de teclado.")
    print(f"Threshold ativo: {threshold}")
    print("-" * 80)

    cap = AudioCapture()
    if not cap.start():
        print("[ERRO] Falha ao iniciar microfone PyAudio.")
        return

    det = OpenWakeWordDetector(wake_word="Okay KON", threshold=threshold, cooldown_seconds=1.0)
    det._initialize_model()

    print(f"Modelos carregados: {det._active_models}")
    print("Iniciando bateria de 10 tentativas ao vivo...")
    print("-" * 80)

    results = []

    try:
        for r_num in range(1, total_rounds + 1):
            print(f"\n>>> [TENTATIVA {r_num} DE {total_rounds}] <<<")
            print("Prepare-se... Fale 'Okay KON' agora!")

            # Flush previous queue chunks
            while cap.read_chunk(timeout=0.01) is not None:
                pass

            t_start = time.time()
            triggered = False
            max_score = 0.0
            peak_rms = 0.0

            while time.time() - t_start < round_duration:
                chunk = cap.read_chunk(timeout=0.1)
                if not chunk or len(chunk) < 2560:
                    continue

                samples = np.frombuffer(chunk[:2560], dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                if rms > peak_rms:
                    peak_rms = rms

                # Predict
                preds = det._model.predict(samples[:1280])
                s = float(preds.get("okay_kon", 0.0))
                if s > max_score:
                    max_score = s

                if s >= threshold:
                    triggered = True
                    break

            if triggered:
                print(f"  ✅ ATIVADO POR VOZ! (Score: {max_score:.4f} >= {threshold}, RMS: {peak_rms:.1f})")
            else:
                print(f"  ❌ NÃO ATIVOU. (Score máximo: {max_score:.4f} < {threshold}, RMS: {peak_rms:.1f})")

            results.append({
                "round": r_num,
                "score": max_score,
                "rms": peak_rms,
                "triggered": triggered
            })

            time.sleep(1.0)

    finally:
        cap.stop()

    print("\n" + "=" * 80)
    print("                     RELATÓRIO DO TESTE AO VIVO")
    print("=" * 80)
    print(f"{'#':<3} | {'Score Máximo':<15} | {'Pico RMS':<12} | {'Ativou por Voz?':<18}")
    print("-" * 80)

    for r in results:
        status_str = "✅ SIM" if r["triggered"] else "❌ NÃO"
        print(f"{r['round']:<3} | {r['score']:<15.4f} | {r['rms']:<12.1f} | {status_str:<18}")

    total_activations = sum(1 for r in results if r["triggered"])
    success_rate = (total_activations / total_rounds) * 100

    print("-" * 80)
    print(f"Total de ativações por voz: {total_activations} / {total_rounds} ({success_rate:.1f}%)")
    print(f"Threshold utilizado: {threshold}")

    if total_activations >= 8:
        print("\n>>> CRITÉRIO DE ACEITE ATINGIDO: APROVADO! (>= 8/10 ativadas) <<<")
    else:
        print(f"\n>>> CRITÉRIO DE ACEITE NÃO ATINGIDO: REPROVADO ({total_activations}/10 < 8) <<<")

    print("=" * 80)


if __name__ == "__main__":
    main()
