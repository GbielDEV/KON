"""
Evaluates all real voice recordings in data/recordings/positive_okay_kon/
against the okay_kon.onnx model and displays the true score distribution.
"""
import glob
import os
import sys
import wave
import numpy as np
from openwakeword.model import Model

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_wav(filepath: str) -> tuple[np.ndarray, int]:
    with wave.open(filepath, "rb") as wf:
        ch = wf.getnchannels()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    arr = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        arr = arr[::ch]
    if sr != 16000 and len(arr) > 0:
        target_len = int(len(arr) * 16000 / sr)
        arr = np.interp(
            np.linspace(0, len(arr), target_len, endpoint=False),
            np.arange(len(arr)),
            arr
        ).astype(np.int16)
    return arr, 16000


def evaluate_audio(model: Model, pcm: np.ndarray) -> tuple[float, float]:
    # Reset model state with zeros
    for _ in range(15):
        model.predict(np.zeros(1280, dtype=np.int16))

    samples = np.pad(pcm, (1600, 1600), mode="constant")
    max_score = 0.0
    rms_vals = []

    for i in range(0, len(samples) - 1280 + 1, 1280):
        chunk = samples[i:i + 1280]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
        rms_vals.append(rms)
        preds = model.predict(chunk)
        s = preds.get("okay_kon", 0.0)
        if s > max_score:
            max_score = float(s)

    peak_rms = max(rms_vals) if rms_vals else 0.0
    return max_score, peak_rms


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    recordings_dir = os.path.join(root_dir, "data", "recordings", "positive_okay_kon")
    model_path = os.path.join(root_dir, "data", "models", "okay_kon.onnx")

    wav_files = sorted(glob.glob(os.path.join(recordings_dir, "*.wav")))

    print("=" * 80)
    print("   AVALIAÇÃO DE GRAVAÇÕES REAIS DA SUA VOZ — OKAY_KON.ONNX")
    print("=" * 80)
    print(f"Modelo: {model_path}")
    print(f"Diretório de gravações: {recordings_dir}")
    print(f"Total de arquivos encontrados: {len(wav_files)}")
    print("-" * 80)

    if not wav_files:
        print("[AVISO] Nenhuma gravação encontrada em data/recordings/positive_okay_kon/.")
        print("Por favor, execute primeiro o script de gravação:")
        print("    .venv\\Scripts\\python.exe scripts/record_wake_word_samples.py")
        return

    model = Model(wakeword_models=[model_path], inference_framework="onnx")

    results = []
    for filepath in wav_files:
        fname = os.path.basename(filepath)
        pcm, _ = load_wav(filepath)
        score, peak_rms = evaluate_audio(model, pcm)
        results.append({
            "name": fname,
            "duration": len(pcm) / 16000,
            "rms": peak_rms,
            "score": score,
            "t38": score >= 0.38,
            "t30": score >= 0.30,
        })

    print(f"{'Arquivo':<16} | {'Duração':<8} | {'Pico RMS':<10} | {'Score Real':<12} | {'>=0.38':<8} | {'>=0.30':<8}")
    print("-" * 80)
    for r in results:
        c38 = "SIM" if r["t38"] else "NÃO"
        c30 = "SIM" if r["t30"] else "NÃO"
        print(f"{r['name']:<16} | {r['duration']:5.1f}s   | {r['rms']:<10.1f} | {r['score']:<12.4f} | {c38:<8} | {c30:<8}")

    scores = [r["score"] for r in results]
    print("-" * 80)
    print(f"MÉDIA DE SCORE:   {np.mean(scores):.4f}")
    print(f"MÍNIMO REGISTRADO: {np.min(scores):.4f}")
    print(f"MÁXIMO REGISTRADO: {np.max(scores):.4f}")
    print(f"MEDIANA:          {np.median(scores):.4f}")
    print("-" * 80)
    passes_38 = sum(1 for r in results if r["t38"])
    passes_30 = sum(1 for r in results if r["t30"])
    print(f"Ativações com threshold 0.38: {passes_38} / {len(results)} ({passes_38/len(results)*100:.1f}%)")
    print(f"Ativações com threshold 0.30: {passes_30} / {len(results)} ({passes_30/len(results)*100:.1f}%)")
    print("=" * 80)


if __name__ == "__main__":
    main()
