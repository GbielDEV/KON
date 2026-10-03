"""
Interactive CLI recording tool to collect real voice samples of 'Okay KON'
from the user's physical microphone.

Saves 16kHz 16-bit mono PCM WAV files into:
  data/recordings/positive_okay_kon/sample_XX.wav
"""
import os
import sys
import time
import wave
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from voice_assistant.audio.capture import AudioCapture


def record_sample(cap: AudioCapture, duration: float = 2.2) -> tuple[np.ndarray, float]:
    """Records audio for `duration` seconds and returns (int16_samples, peak_rms)."""
    # Flush any leftover chunks in queue
    while cap.read_chunk(timeout=0.01) is not None:
        pass

    chunks = []
    rms_list = []
    t_start = time.time()

    print("  🔴 GRAVANDO... Fale agora: 'Okay KON'!", end="", flush=True)

    while time.time() - t_start < duration:
        chunk = cap.read_chunk(timeout=0.1)
        if chunk and len(chunk) >= 2560:
            chunks.append(chunk[:2560])
            s = np.frombuffer(chunk[:2560], dtype=np.int16)
            rms = float(np.sqrt(np.mean(s.astype(np.float32) ** 2)))
            rms_list.append(rms)

    print("  ⏹ Pronto!")

    if not chunks:
        return np.array([], dtype=np.int16), 0.0

    raw_bytes = b"".join(chunks)
    samples = np.frombuffer(raw_bytes, dtype=np.int16)
    peak_rms = max(rms_list) if rms_list else 0.0
    return samples, peak_rms


def save_wav(filepath: str, samples: np.ndarray, sample_rate: int = 16000) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(root_dir, "data", "recordings", "positive_okay_kon")
    os.makedirs(target_dir, exist_ok=True)

    total_target = 25
    guide = [
        # (range_start, range_end, prompt)
        (1, 5, "Tom de voz normal, postura natural (~1 metro de distância)"),
        (6, 10, "Tom de voz mais baixo / suave (~1 metro de distância)"),
        (11, 15, "Distância maior (~1.5m a 2.0m do microfone)"),
        (16, 20, "Mais perto do microfone (~30cm a 50cm, volume normal)"),
        (21, 25, "Variações naturais (pronúncia rápida, casual ou mais lenta)"),
    ]

    print("=" * 75)
    print("      GRAVAÇÃO DE AMOSTRAS REAIS DA SUA VOZ — 'Okay KON'")
    print("=" * 75)
    print(f"Diretório de destino: {target_dir}")
    print(f"Objetivo: Coletar {total_target} gravações reais da sua voz para treinar e validar")
    print("o modelo com a acústica real do seu microfone e a sua anatomia vocal.")
    print("-" * 75)
    print("Como funciona:")
    print("  1. Leia a instrução de cada tomada.")
    print("  2. Pressione [ENTER] quando estiver pronto.")
    print("  3. Diga 'Okay KON' naturalmente enquanto estiver marcando 'GRAVANDO'.")
    print("  4. O script valida o áudio e salva automaticamente.")
    print("  (Você pode pressionar Ctrl+C a qualquer momento para pausar).")
    print("-" * 75)

    cap = AudioCapture()
    if not cap.start():
        print("[ERRO] Falha ao iniciar microfone PyAudio.")
        return

    try:
        sample_idx = 1
        # Check existing files
        while os.path.exists(os.path.join(target_dir, f"sample_{sample_idx:02d}.wav")):
            sample_idx += 1

        if sample_idx > 1:
            print(f"[INFO] Foram encontradas {sample_idx - 1} gravações anteriores.")
            resp = input(f"Deseja continuar a partir da amostra {sample_idx}? (S/N) [S]: ").strip().lower()
            if resp == "n":
                sample_idx = 1

        while sample_idx <= total_target:
            # Find guide instruction
            instruction = "Voz natural"
            for start, end, text in guide:
                if start <= sample_idx <= end:
                    instruction = text
                    break

            print(f"\n[{sample_idx}/{total_target}] Instrução: {instruction}")
            user_input = input("Pressione [ENTER] para gravar (ou 'q' para sair): ")
            if user_input.strip().lower() == "q":
                break

            samples, peak_rms = record_sample(cap, duration=2.2)

            if len(samples) == 0 or peak_rms < 100:
                print(f"  ⚠️  Áudio muito baixo ou silêncio detectado (Pico RMS: {peak_rms:.1f}).")
                retry = input("  Deseja descartar e tentar novamente? (S/N) [S]: ").strip().lower()
                if retry != "n":
                    continue

            filename = f"sample_{sample_idx:02d}.wav"
            filepath = os.path.join(target_dir, filename)
            save_wav(filepath, samples)
            print(f"  ✅ Salvo com sucesso: {filename} (Pico RMS: {peak_rms:.1f}, Duração: {len(samples)/16000:.1f}s)")
            sample_idx += 1

        print("\n" + "=" * 75)
        recorded_count = len([f for f in os.listdir(target_dir) if f.endswith(".wav")])
        print(f"Gravações concluídas! Total de amostras reais disponíveis: {recorded_count}")
        print("=" * 75)

    finally:
        cap.stop()


if __name__ == "__main__":
    main()
