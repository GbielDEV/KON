"""
Evaluation and score distribution benchmark for okay_kon.onnx.
Tests the model against 10 diverse acoustic voice profiles (simulating male, female,
soft, normal, distant, loud utterances of 'Okay KON') as well as silence and ambient noise.
Outputs the score distribution table comparing thresholds: 0.50, 0.40, 0.38, 0.35, 0.30.
"""
import os
import sys
import tempfile
import wave
import numpy as np
import pyttsx3
from openwakeword.model import Model

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def synthesize_base(phrase: str = "Okay KON", rate: int = 160) -> np.ndarray:
    engine = pyttsx3.init("sapi5")
    engine.setProperty("rate", rate)
    for v in engine.getProperty("voices"):
        if "maria" in v.name.lower() or "brazil" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        p = tmp.name
    try:
        engine.save_to_file(phrase, p)
        engine.runAndWait()
        with wave.open(p, "rb") as wf:
            ch = wf.getnchannels()
            fr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        arr = np.frombuffer(raw, dtype=np.int16)
        if ch > 1:
            arr = arr[::ch]
        if fr != 16000 and len(arr) > 0:
            target_len = int(len(arr) * 16000 / fr)
            arr = np.interp(
                np.linspace(0, len(arr), target_len, endpoint=False),
                np.arange(len(arr)),
                arr
            ).astype(np.int16)
        return arr
    finally:
        del engine
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def pitch_shift(pcm: np.ndarray, factor: float) -> np.ndarray:
    if factor == 1.0 or len(pcm) == 0:
        return pcm
    new_len = int(len(pcm) / factor)
    res = np.interp(
        np.linspace(0, len(pcm), new_len, endpoint=False),
        np.arange(len(pcm)),
        pcm
    )
    final = np.interp(
        np.linspace(0, len(res), len(pcm), endpoint=False),
        np.arange(len(res)),
        res
    ).astype(np.int16)
    return final


def test_audio_with_model(model: Model, pcm: np.ndarray) -> float:
    # Reset model state by feeding zeros
    for _ in range(15):
        model.predict(np.zeros(1280, dtype=np.int16))

    # Pad with 1600 samples before and after
    padded = np.pad(pcm, (1600, 1600), mode="constant")
    max_score = 0.0
    for i in range(0, len(padded) - 1280 + 1, 1280):
        chunk = padded[i:i + 1280]
        preds = model.predict(chunk)
        s = preds.get("okay_kon", 0.0)
        if s > max_score:
            max_score = float(s)
    return max_score


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(root, "data", "models", "okay_kon.onnx")

    print("=" * 80)
    print("  AVALIAÇÃO QUANTITATIVA E DISTRIBUIÇÃO DE SCORES — MODELO OKAY_KON.ONNX")
    print("=" * 80)
    print(f"Modelo avaliado: {model_path} ({os.path.getsize(model_path)} bytes)")

    oww = Model(wakeword_models=[model_path], inference_framework="onnx")

    # 1. Negative control tests: Silence and Ambient Room Noise
    print("\n--- CONTROLE NEGATIVO (SILÊNCIO E RUÍDO DE FUNDO) ---")
    oww.predict(np.zeros(1280, dtype=np.int16))
    silence_scores = []
    for _ in range(25):
        preds = oww.predict(np.zeros(1280, dtype=np.int16))
        silence_scores.append(preds.get("okay_kon", 0.0))
    print(f"Score Máximo em Silêncio Absoluto (Zeros): {max(silence_scores):.6f}")

    noise_scores = []
    for _ in range(35):
        noise = (np.random.randn(1280) * 120).astype(np.int16)  # ~120 RMS
        preds = oww.predict(noise)
        noise_scores.append(preds.get("okay_kon", 0.0))
    print(f"Score Máximo em Ruído Ambiente (120 RMS):   {max(noise_scores):.6f}")

    # 2. 10 Trials of 'Okay KON' with diverse voice acoustics
    print("\n--- BATERIA DE 10 TENTATIVAS DE 'Okay KON' COM VARIAÇÃO ACÚSTICA ---")
    base_pcm = synthesize_base("Okay KON", rate=160)

    # 10 configurations simulating real human vocal variation
    trials = [
        {"name": "Voz Padrão (1.00x pitch, 1.0x vol)", "pitch": 1.00, "vol": 1.0, "rate": 160},
        {"name": "Voz Grave / Masculina (0.90x pitch)", "pitch": 0.90, "vol": 1.0, "rate": 160},
        {"name": "Voz Grave Profunda (0.86x pitch)", "pitch": 0.86, "vol": 0.9, "rate": 155},
        {"name": "Voz Aguda / Feminina (1.12x pitch)", "pitch": 1.12, "vol": 1.0, "rate": 165},
        {"name": "Voz Aguda Suave (1.16x pitch)", "pitch": 1.16, "vol": 0.8, "rate": 170},
        {"name": "Voz Distante (~2m, vol 0.5x)", "pitch": 1.00, "vol": 0.5, "rate": 160},
        {"name": "Voz Perto / Alta (vol 1.3x)", "pitch": 1.00, "vol": 1.3, "rate": 160},
        {"name": "Pronúncia Rápida (rate 185)", "pitch": 1.02, "vol": 1.0, "rate": 185},
        {"name": "Pronúncia Lenta (rate 140)", "pitch": 0.96, "vol": 1.0, "rate": 140},
        {"name": "Voz Grave + Distante (0.92x, 0.6x vol)", "pitch": 0.92, "vol": 0.6, "rate": 155},
    ]

    results = []
    for idx, t in enumerate(trials, 1):
        raw = synthesize_base("Okay KON", rate=t["rate"]) if t["rate"] != 160 else base_pcm
        shifted = pitch_shift(raw, t["pitch"])
        scaled = np.clip(shifted.astype(np.float32) * t["vol"], -32768, 32767).astype(np.int16)
        score = test_audio_with_model(oww, scaled)
        results.append({
            "idx": idx,
            "name": t["name"],
            "score": score,
            "t50": score >= 0.50,
            "t40": score >= 0.40,
            "t38": score >= 0.38,
            "t35": score >= 0.35,
            "t30": score >= 0.30,
        })

    print(f"\n{'#':<3} | {'Perfil de Voz / Condição':<38} | {'Score':<8} | {'>=0.50':<7} | {'>=0.40':<7} | {'>=0.38':<7} | {'>=0.35':<7}")
    print("-" * 80)
    for r in results:
        c50 = "SIM" if r["t50"] else "NÃO"
        c40 = "SIM" if r["t40"] else "NÃO"
        c38 = "SIM" if r["t38"] else "NÃO"
        c35 = "SIM" if r["t35"] else "NÃO"
        print(f"{r['idx']:<3} | {r['name']:<38} | {r['score']:<8.4f} | {c50:<7} | {c40:<7} | {c38:<7} | {c35:<7}")

    scores = [r["score"] for r in results]
    print("-" * 80)
    print(f"MÉDIA DE SCORE:   {np.mean(scores):.4f}")
    print(f"MÍNIMO REGISTRADO: {np.min(scores):.4f}")
    print(f"MÁXIMO REGISTRADO: {np.max(scores):.4f}")
    print(f"MEDIANA:          {np.median(scores):.4f}")
    print("-" * 80)
    print(f"Ativações com threshold 0.50: {sum(1 for r in results if r['t50'])} / 10 ({sum(1 for r in results if r['t50'])*10}%)")
    print(f"Ativações com threshold 0.40: {sum(1 for r in results if r['t40'])} / 10 ({sum(1 for r in results if r['t40'])*10}%)")
    print(f"Ativações com threshold 0.38: {sum(1 for r in results if r['t38'])} / 10 ({sum(1 for r in results if r['t38'])*10}%) [ESCOLHIDO]")
    print(f"Ativações com threshold 0.35: {sum(1 for r in results if r['t35'])} / 10 ({sum(1 for r in results if r['t35'])*10}%)")
    print(f"Ativações com threshold 0.30: {sum(1 for r in results if r['t30'])} / 10 ({sum(1 for r in results if r['t30'])*10}%)")
    print("=" * 80)


if __name__ == "__main__":
    main()
