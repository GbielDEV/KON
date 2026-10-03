"""
Generates an ONNX wake word model for 'Okay KON' compatible with openWakeWord.
Synthesizes training clips using pyttsx3, extracts openWakeWord acoustic embeddings,
trains a binary neural classifier, and exports to data/models/okay_kon.onnx.
"""
import os
from typing import Optional
import tempfile
import wave
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import pyttsx3
from openwakeword.utils import AudioFeatures


class OkayKonClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16 * 96, 64),
            nn.ReLU(),
            nn.Dropout(0.1),
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

        # Convert to int16 numpy array
        arr = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            arr = arr[::channels]  # Stereo to mono

        # Resample to 16000 if needed
        if framerate != 16000 and len(arr) > 0:
            target_len = int(len(arr) * 16000 / framerate)
            arr = np.interp(
                np.linspace(0, len(arr), target_len, endpoint=False),
                np.arange(len(arr)),
                arr
            ).astype(np.int16)

        return arr
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def build_okay_kon_model(output_path: Optional[str] = None) -> str:
    if output_path is None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = os.path.join(root_dir, "data", "models", "okay_kon.onnx")
    print("="*50)
    print(" TREINANDO MODELO ONNX 'Okay KON' PARA OPENWAKEWORD")
    print("="*50)

    positive_phrases = [
        "Okay KON",
        "Ok KON",
        "Okay Kon",
        "Ok Kon",
        "OK KON",
        "O quê KON",
        "Ei KON",
        "Hey KON",
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
    ]

    af = AudioFeatures()
    positive_features = []
    negative_features = []

    print("[1/4] Gerando amostras positivas ('Okay KON')...")
    for phrase in positive_phrases:
        for rate in [140, 160, 175, 195]:
            pcm = synthesize_phrase_to_pcm(phrase, rate=rate)
            if len(pcm) < 16000:
                # Pad to at least 1.5s
                pad_left = np.zeros(2000, dtype=np.int16)
                pad_right = np.zeros(max(0, 24000 - len(pcm) - 2000), dtype=np.int16)
                pcm = np.concatenate([pad_left, pcm, pad_right])

            # Extract features across audio chunks
            for i in range(0, len(pcm) - 1280 + 1, 1280):
                chunk = pcm[i:i + 1280]
                af(chunk)
                feat = af.get_features(16)
                if feat.shape == (1, 16, 96):
                    # Data augmentation with slight noise
                    noise = (np.random.randn(*feat.shape) * 0.02).astype(np.float32)
                    positive_features.append(feat.copy())
                    positive_features.append(feat + noise)

    print(f"      {len(positive_features)} features positivas geradas.")

    print("[2/4] Gerando amostras negativas...")
    # 1. Negative phrases
    for phrase in negative_phrases:
        for rate in [150, 175, 200]:
            pcm = synthesize_phrase_to_pcm(phrase, rate=rate)
            for i in range(0, len(pcm) - 1280 + 1, 1280):
                chunk = pcm[i:i + 1280]
                af(chunk)
                feat = af.get_features(16)
                if feat.shape == (1, 16, 96):
                    negative_features.append(feat.copy())

    # 2. Silence and noise
    for _ in range(50):
        noise_chunk = (np.random.randn(1280) * 150).astype(np.int16)
        af(noise_chunk)
        feat = af.get_features(16)
        if feat.shape == (1, 16, 96):
            negative_features.append(feat.copy())

    print(f"      {len(negative_features)} features negativas geradas.")

    # Convert to tensors
    X_pos = np.vstack(positive_features)
    y_pos = np.ones((len(X_pos), 1), dtype=np.float32)

    X_neg = np.vstack(negative_features)
    y_neg = np.zeros((len(X_neg), 1), dtype=np.float32)

    X = np.vstack([X_pos, X_neg])
    y = np.vstack([y_pos, y_neg])

    # Shuffle
    indices = np.random.permutation(len(X))
    X_tensor = torch.tensor(X[indices], dtype=torch.float32)
    y_tensor = torch.tensor(y[indices], dtype=torch.float32)

    print("[3/4] Treinando rede neural binária...")
    model = OkayKonClassifier()
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.002, weight_decay=1e-4)

    dataset = torch.utils.data.TensorDataset(X_tensor, y_tensor)
    loader = torch.utils.data.DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(25):
        epoch_loss = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            pred = model(batch_x)
            loss = criterion(pred, batch_y)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

    print(f"      Treinamento concluído. Perda final: {epoch_loss / len(loader):.4f}")

    print(f"[4/4] Exportando para ONNX: '{output_path}'...")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    model.eval()
    dummy_input = torch.randn(1, 16, 96, dtype=torch.float32)

    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["x.1"],
        output_names=["output"],
        dynamic_axes={"x.1": {0: "batch_size"}, "output": {0: "batch_size"}},
    )

    print(f"      Modelo 'okay_kon.onnx' exportado com sucesso ({os.path.getsize(output_path)} bytes)!")
    return output_path


if __name__ == "__main__":
    build_okay_kon_model()
