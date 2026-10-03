"""
Diagnostic script to test and display the exact real-time scores of okay_kon
and openWakeWord models when speaking 'Okay KON' through the physical microphone.
"""
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import OpenWakeWordDetector


def main():
    print("=" * 75)
    print("     DIAGNÓSTICO ISOLADO DE SCORES DO MODELO DE WAKE WORD ('Okay KON')")
    print("=" * 75)
    print("Este script mede a distribuição real de scores do modelo openWakeWord.")
    print("Modelos monitorados: 'okay_kon', 'alexa_v0.1', 'hey_jarvis_v0.1'")
    print("-" * 75)

    cap = AudioCapture()
    if not cap.start():
        print("[ERRO] Não foi possível iniciar o microfone.")
        return

    det = OpenWakeWordDetector(wake_word="Okay KON", threshold=0.10)
    det._initialize_model()

    print(f"Modelos carregados: {det._active_models}")
    print("\nInstruções:")
    print("  Fale 'Okay KON' naturalmente a ~1 metro do microfone quando indicado.")
    print("  O script registrará o score máximo atingido em cada tentativa.")
    print("-" * 75)

    attempts = []

    for round_num in range(1, 11):
        print(f"\n>>> TENTATIVA {round_num} DE 10 <<<")
        print("Prepare-se... Fale 'Okay KON' agora!")

        t_start = time.time()
        max_scores = {m: 0.0 for m in det._active_models}
        rms_values = []

        # Listen for 3.5 seconds per attempt
        while time.time() - t_start < 3.5:
            chunk = cap.read_chunk(timeout=0.2)
            if not chunk or len(chunk) < 2560:
                continue

            samples = np.frombuffer(chunk[:2560], dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
            rms_values.append(rms)

            preds = det._model.predict(samples[:1280])
            for m, s in preds.items():
                if s > max_scores.get(m, 0.0):
                    max_scores[m] = float(s)

        kon_score = max_scores.get("okay_kon", 0.0)
        peak_rms = max(rms_values) if rms_values else 0.0

        print(f"  [Tentativa {round_num:2d}] Pico RMS: {peak_rms:5.1f} | Score 'okay_kon': {kon_score:.4f}")
        for m, s in max_scores.items():
            if m != "okay_kon":
                print(f"                 Score '{m}': {s:.4f}")

        attempts.append({
            "round": round_num,
            "okay_kon": kon_score,
            "rms": peak_rms,
            "all": max_scores
        })
        time.sleep(1.0)

    cap.stop()

    print("\n" + "=" * 75)
    print("                      RELATÓRIO DA DISTRIBUIÇÃO DE SCORES")
    print("=" * 75)
    print(f"{'#':<3} | {'Score okay_kon':<15} | {'RMS Pico':<10} | {'>=0.50':<8} | {'>=0.40':<8} | {'>=0.35':<8} | {'>=0.30':<8}")
    print("-" * 75)

    scores_list = [a["okay_kon"] for a in attempts]
    for a in attempts:
        s = a["okay_kon"]
        r = a["rms"]
        c50 = "SIM" if s >= 0.50 else "NÃO"
        c40 = "SIM" if s >= 0.40 else "NÃO"
        c35 = "SIM" if s >= 0.35 else "NÃO"
        c30 = "SIM" if s >= 0.30 else "NÃO"
        print(f"{a['round']:<3} | {s:<15.4f} | {r:<10.1f} | {c50:<8} | {c40:<8} | {c35:<8} | {c30:<8}")

    print("-" * 75)
    print(f"Média:   {np.mean(scores_list):.4f}")
    print(f"Mínimo:  {np.min(scores_list):.4f}")
    print(f"Máximo:  {np.max(scores_list):.4f}")
    print(f"Mediana: {np.median(scores_list):.4f}")
    print(f"Ativações com threshold 0.50: {sum(1 for s in scores_list if s >= 0.50)} / 10")
    print(f"Ativações com threshold 0.40: {sum(1 for s in scores_list if s >= 0.40)} / 10")
    print(f"Ativações com threshold 0.35: {sum(1 for s in scores_list if s >= 0.35)} / 10")
    print(f"Ativações com threshold 0.30: {sum(1 for s in scores_list if s >= 0.30)} / 10")
    print("=" * 75)


if __name__ == "__main__":
    main()
