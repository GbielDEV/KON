"""
Retrains okay_kon.onnx incorporating REAL human voice recordings
from data/recordings/positive_okay_kon/ alongside balanced negative samples.
"""
import glob
import os
import sys
import tempfile
import wave
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import pyttsx3
from openwakeword.utils import AudioFeatures

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_wav_pcm(filepath: str) -> np.ndarray:
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
    return arr


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


def synthesize_base_pcm(phrase: str, rate: int = 160) -> np.ndarray:
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


def extract_features_from_pcm(af: AudioFeatures, pcm: np.ndarray, is_positive: bool = True):
    """Feeds PCM chunk by chunk into AudioFeatures and labels appropriate ending/all chunks."""
    feats = []
    af.reset()
    n_chunks = len(pcm) // 1280
    if n_chunks == 0:
        return feats

    for c_idx in range(n_chunks):
        chunk = pcm[c_idx * 1280:(c_idx + 1) * 1280]
        af(chunk)
        feat = af.get_features(16)
        if feat.shape == (1, 16, 96):
            if is_positive:
                # Ending 2 chunks of positive wake word
                if c_idx >= n_chunks - 2:
                    feats.append(feat.copy())
            else:
                feats.append(feat.copy())
    return feats


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    recordings_dir = os.path.join(root_dir, "data", "recordings", "positive_okay_kon")
    output_path = os.path.join(root_dir, "data", "models", "okay_kon.onnx")

    wav_files = sorted(glob.glob(os.path.join(recordings_dir, "*.wav")))

    print("=" * 75)
    print("   TREINAMENTO v4 DO MODELO 'Okay KON' COM DADOS REAIS DE VOZ")
    print("=" * 75)
    print(f"Gravações reais encontradas: {len(wav_files)}")
    print(f"Destino do modelo ONNX: {output_path}")
    print("-" * 75)

    if not wav_files:
        print("[ERRO] Nenhuma gravação real encontrada!")
        print("Execute primeiro: .venv\\Scripts\\python.exe scripts/record_wake_word_samples.py")
        return

    af = AudioFeatures()
    positive_features = []
    negative_features = []

    # 1. Process Real Recordings with acoustic augmentation
    print("\n[1/4] Extraindo features das gravações REAIS da sua voz...")
    for idx, filepath in enumerate(wav_files, 1):
        raw_pcm = load_wav_pcm(filepath)
        if len(raw_pcm) < 6400:
            raw_pcm = np.pad(raw_pcm, (1600, 1600), mode="constant")

        # Variations: original, gain 0.8x, gain 1.25x, pitch 0.96x, pitch 1.04x
        variations = [
            raw_pcm,
            (raw_pcm.astype(np.float32) * 0.8).astype(np.int16),
            (raw_pcm.astype(np.float32) * 1.25).clip(-32768, 32767).astype(np.int16),
            pitch_shift(raw_pcm, 0.96),
            pitch_shift(raw_pcm, 1.04),
        ]

        for pcm_var in variations:
            pos_f = extract_features_from_pcm(af, pcm_var, is_positive=True)
            for f in pos_f:
                positive_features.append(f)
                # Slight noise jitter
                jitter = (np.random.randn(*f.shape) * 0.01).astype(np.float32)
                positive_features.append(f + jitter)

    print(f"      {len(positive_features)} features positivas extraídas a partir de voz real humana.")

    # 2. Add Synthetic Positive anchors (to cover 'OK KON', 'Ok KON')
    print("\n[2/4] Adicionando âncoras sintéticas complementares...")
    synth_phrases = ["Okay KON", "Ok KON", "OK KON", "Ei KON", "Hey KON"]
    for ph in synth_phrases:
        for rate in [150, 170]:
            pcm = synthesize_base_pcm(ph, rate=rate)
            if len(pcm) < 6400:
                pcm = np.pad(pcm, (1600, 1600), mode="constant")
            pos_f = extract_features_from_pcm(af, pcm, is_positive=True)
            for f in pos_f:
                positive_features.append(f)

    print(f"      Total de features positivas (Real + Sintético): {len(positive_features)}")

    # 3. Generate Negative Samples (Silence, Room Noise, Unrelated Portuguese)
    print("\n[3/4] Gerando amostras NEGATIVAS rigorosas (silêncio, ruído e frases gerais)...")
    negative_phrases = [
        "olá assistente",
        "bom dia como vai",
        "abrir o navegador agora",
        "qual o horário atual",
        "tocar uma música",
        "navegador de internet",
        "computador ligado",
        "janela aberta",
        "teste de som do microfone",
        "boa noite até logo",
        "sistema operacional windows",
        "abra o google chrome",
        "abra o bloco de notas",
        "abra meus downloads",
        "pesquise por inteligência artificial",
        "abra a calculadora",
        "fechar esta janela",
        "sim por favor",
        "não obrigado",
        "muito bem",
        "vamos lá",
    ]
    for ph in negative_phrases:
        pcm = synthesize_base_pcm(ph, rate=165)
        neg_f = extract_features_from_pcm(af, pcm, is_positive=False)
        negative_features.extend(neg_f)

    # Pure silence (zeros)
    print("      Extraindo silêncio absoluto (zeros)...")
    af.reset()
    for _ in range(150):
        af(np.zeros(1280, dtype=np.int16))
        f = af.get_features(16)
        if f.shape == (1, 16, 96):
            negative_features.append(f.copy())

    # Room noise (RMS 30 to 450)
    print("      Extraindo ruído de piso elétrico e ambiente...")
    for rms in [30, 70, 120, 200, 320, 450]:
        af.reset()
        for _ in range(40):
            noise = (np.random.randn(1280) * rms).astype(np.int16)
            af(noise)
            f = af.get_features(16)
            if f.shape == (1, 16, 96):
                negative_features.append(f.copy())

    print(f"      {len(negative_features)} features negativas geradas.")
    print(f"      Proporção: {len(positive_features)} positivas vs {len(negative_features)} negativas (1:{len(negative_features)/len(positive_features):.1f})")

    # 4. Train Model
    print("\n[4/4] Treinando rede neural com peso calibrado para voz real...")
    X_pos = np.vstack(positive_features)
    y_pos = np.ones((len(X_pos), 1), dtype=np.float32)

    X_neg = np.vstack(negative_features)
    y_neg = np.zeros((len(X_neg), 1), dtype=np.float32)

    X = np.vstack([X_pos, X_neg])
    y = np.vstack([y_pos, y_neg])

    idx_perm = np.random.permutation(len(X))
    X_t = torch.tensor(X[idx_perm], dtype=torch.float32)
    y_t = torch.tensor(y[idx_perm], dtype=torch.float32)

    model = nn.Sequential(
        nn.Flatten(),
        nn.Linear(16 * 96, 64),
        nn.ReLU(),
        nn.Dropout(0.2),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Linear(32, 1),
    )

    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([1.3]))
    optimizer = optim.AdamW(model.parameters(), lr=0.0012, weight_decay=5e-4)

    dataset = torch.utils.data.TensorDataset(X_t, y_t)
    loader = torch.utils.data.DataLoader(dataset, batch_size=64, shuffle=True)

    model.train()
    for epoch in range(35):
        loss_total = 0.0
        for bx, by in loader:
            optimizer.zero_grad()
            out = model(bx)
            loss = criterion(out, by)
            loss.backward()
            optimizer.step()
            loss_total += loss.item()

    print(f"      Treinamento concluído. Perda final: {loss_total / len(loader):.4f}")

    class ExportNet(nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base
            self.sig = nn.Sigmoid()

        def forward(self, x):
            return self.sig(self.base(x))

    export_m = ExportNet(model)
    export_m.eval()

    # Export to ONNX
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    dummy = torch.randn(1, 16, 96, dtype=torch.float32)
    torch.onnx.export(
        export_m,
        dummy,
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["x.1"],
        output_names=["output"],
        dynamic_axes={"x.1": {0: "batch_size"}, "output": {0: "batch_size"}},
        dynamo=False,
    )
    print(f"\n[SUCESSO] Modelo retreinado salvo em: '{output_path}' ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
