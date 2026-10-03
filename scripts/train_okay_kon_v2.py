"""
Retrains okay_kon.onnx with strict negative sampling:
- Zeros / Silence -> Label 0.0 (Negative)
- Ambient / Gaussian Noise -> Label 0.0 (Negative)
- Unrelated Portuguese speech -> Label 0.0 (Negative)
- "Okay KON" final acoustic frames -> Label 1.0 (Positive)
"""
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
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class OkayKonClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16 * 96, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        return self.net(x)


def synthesize_phrase_to_pcm(phrase: str, rate: int = 175) -> np.ndarray:
    """Synthesizes phrase to 16kHz mono int16 array using pyttsx3."""
    engine = pyttsx3.init("sapi5")
    engine.setProperty("rate", rate)
    for v in engine.getProperty("voices"):
        if "maria" in v.name.lower() or "brazil" in v.name.lower():
            engine.setProperty("voice", v.id)
            break

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        engine.save_to_file(phrase, tmp_path)
        engine.runAndWait()

        with wave.open(tmp_path, "rb") as wf:
            channels = wf.getnchannels()
            _ = wf.getsampwidth()
            framerate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())

        arr = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            arr = arr[::channels]

        if framerate != 16000 and len(arr) > 0:
            target_len = int(len(arr) * 16000 / framerate)
            arr = np.interp(
                np.linspace(0, len(arr), target_len, endpoint=False),
                np.arange(len(arr)),
                arr
            ).astype(np.int16)

        return arr
    finally:
        del engine
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(root_dir, "data", "models", "okay_kon.onnx")

    print("=" * 65)
    print("   RETREINANDO MODELO ONNX 'Okay KON' COM AMOSTRAGEM NEGATIVA")
    print("=" * 65)

    positive_phrases = [
        "Okay KON",
        "Ok KON",
        "Okay Kon",
        "Ok Kon",
        "OK KON",
        "Ei KON",
        "Hey KON",
        "Kon",
    ]

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
        "silêncio e ruído de fundo",
        "abra o google chrome",
        "abra o bloco de notas",
        "abra meus downloads",
        "pesquise por inteligência artificial",
        "abra a calculadora",
        "mostrar arquivos recentes",
        "fechar esta janela",
        "sim por favor",
        "não obrigado",
        "muito bem",
        "vamos lá",
    ]

    positive_features = []
    negative_features = []

    # 1. Generate Positive Samples
    print("\n[1/4] Gerando amostras POSITIVAS ('Okay KON')...")
    for phrase in positive_phrases:
        for rate in [135, 150, 165, 175, 190, 205]:
            pcm = synthesize_phrase_to_pcm(phrase, rate=rate)
            if len(pcm) < 6400:
                pcm = np.pad(pcm, (1600, 1600), mode="constant")

            # Extract sequentially
            af = AudioFeatures()
            n_chunks = len(pcm) // 1280
            for c_idx in range(n_chunks):
                chunk = pcm[c_idx * 1280:(c_idx + 1) * 1280]
                af(chunk)
                feat = af.get_features(16)
                if feat.shape == (1, 16, 96):
                    # Only the final 2 chunks of the wake word utterance are POSITIVE
                    if c_idx >= n_chunks - 2:
                        positive_features.append(feat.copy())
                        # Data augmentation: slight noise
                        noise = (np.random.randn(*feat.shape) * 0.015).astype(np.float32)
                        positive_features.append(feat + noise)
                    elif c_idx < n_chunks - 3:
                        # Earlier chunks before phrase ends are NEGATIVE
                        negative_features.append(feat.copy())

    print(f"      {len(positive_features)} features positivas geradas.")

    # 2. Generate Negative Samples
    print("\n[2/4] Gerando amostras NEGATIVAS (frases gerais, silêncio e ruídos)...")
    for phrase in negative_phrases:
        for rate in [150, 175, 200]:
            pcm = synthesize_phrase_to_pcm(phrase, rate=rate)
            af = AudioFeatures()
            for c_idx in range(len(pcm) // 1280):
                chunk = pcm[c_idx * 1280:(c_idx + 1) * 1280]
                af(chunk)
                feat = af.get_features(16)
                if feat.shape == (1, 16, 96):
                    negative_features.append(feat.copy())

    # Pure silence (zeros) - CRITICAL!
    print("      Gerando amostras de silêncio absoluto...")
    af_silence = AudioFeatures()
    for _ in range(80):
        af_silence(np.zeros(1280, dtype=np.int16))
        feat = af_silence.get_features(16)
        if feat.shape == (1, 16, 96):
            negative_features.append(feat.copy())

    # Ambient room noise at various RMS levels (50 to 500)
    print("      Gerando amostras de ruído de microfone e ambiente...")
    for rms in [30, 80, 150, 250, 350, 500]:
        af_noise = AudioFeatures()
        for _ in range(30):
            noise_chunk = (np.random.randn(1280) * rms).astype(np.int16)
            af_noise(noise_chunk)
            feat = af_noise.get_features(16)
            if feat.shape == (1, 16, 96):
                negative_features.append(feat.copy())

    print(f"      {len(negative_features)} features negativas geradas.")

    # 3. Balance and Train
    print("\n[3/4] Treinando classificador neural com regularização...")
    X_pos = np.vstack(positive_features)
    y_pos = np.ones((len(X_pos), 1), dtype=np.float32)

    X_neg = np.vstack(negative_features)
    y_neg = np.zeros((len(X_neg), 1), dtype=np.float32)

    X = np.vstack([X_pos, X_neg])
    y = np.vstack([y_pos, y_neg])

    indices = np.random.permutation(len(X))
    X_tensor = torch.tensor(X[indices], dtype=torch.float32)
    y_tensor = torch.tensor(y[indices], dtype=torch.float32)

    # Weight negative class slightly higher to prevent any false positives
    pos_weight = torch.tensor([1.0])
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    # Note: Replace final Sigmoid in network with raw logits during training
    linear_model = nn.Sequential(
        nn.Flatten(),
        nn.Linear(16 * 96, 64),
        nn.ReLU(),
        nn.Dropout(0.2),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Linear(32, 1),
    )
    optimizer = optim.AdamW(linear_model.parameters(), lr=0.001, weight_decay=1e-3)
    dataset = torch.utils.data.TensorDataset(X_tensor, y_tensor)
    loader = torch.utils.data.DataLoader(dataset, batch_size=32, shuffle=True)

    linear_model.train()
    for epoch in range(35):
        loss_sum = 0.0
        for bx, by in loader:
            optimizer.zero_grad()
            logits = linear_model(bx)
            loss = criterion(logits, by)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item()

    print(f"      Treinamento concluído. Perda final: {loss_sum / len(loader):.4f}")

    # Build final ONNX export model with Sigmoid
    class ExportModel(nn.Module):
        def __init__(self, backbone):
            super().__init__()
            self.backbone = backbone
            self.sigmoid = nn.Sigmoid()

        def forward(self, x):
            return self.sigmoid(self.backbone(x))

    export_net = ExportModel(linear_model)
    export_net.eval()

    # 4. Verify on zeros and noise
    print("\n[4/4] Validando predição antes de exportar:")
    with torch.no_grad():
        af_test = AudioFeatures()
        for _ in range(25):
            af_test(np.zeros(1280, dtype=np.int16))
        z_feat = torch.tensor(af_test.get_features(16), dtype=torch.float32)
        score_zero = export_net(z_feat).item()
        print(f"  -> Score em SILÊNCIO (Zeros):  {score_zero:.6f} (esperado: < 0.01)")

        af_test_noise = AudioFeatures()
        for _ in range(25):
            af_test_noise((np.random.randn(1280) * 200).astype(np.int16))
        n_feat = torch.tensor(af_test_noise.get_features(16), dtype=torch.float32)
        score_noise = export_net(n_feat).item()
        print(f"  -> Score em RUÍDO AMBIENTE:    {score_noise:.6f} (esperado: < 0.05)")

    # Export to ONNX
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    dummy_input = torch.randn(1, 16, 96, dtype=torch.float32)
    torch.onnx.export(
        export_net,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["x.1"],
        output_names=["output"],
        dynamic_axes={"x.1": {0: "batch_size"}, "output": {0: "batch_size"}},
        dynamo=False,
    )
    print(f"\n[SUCESSO] Modelo salvo em: '{output_path}' ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
