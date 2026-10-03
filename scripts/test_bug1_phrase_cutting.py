"""
Validation script for BUG 1 — Verifying that words/phrases are never cut off.
Synthesizes 10 medium and long Portuguese phrases with realistic pauses,
transcribes them through SpeechRecognitionEngine with:
- pause_threshold = 1.3s
- non_speaking_duration = 0.8s
- energy_threshold = 350.0
Checks that every trailing word (e.g. 'notas', 'chrome', 'artificial') is intact.
"""
import os
import sys
import time
import tempfile
import pyttsx3
import speech_recognition as sr

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine


def synthesize_phrase(phrase: str, rate: int = 155) -> sr.AudioData:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name

    engine = pyttsx3.init("sapi5")
    for v in engine.getProperty("voices"):
        if "maria" in v.name.lower() or "brazil" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", rate)
    engine.save_to_file(phrase, tmp_path)
    engine.runAndWait()
    del engine

    rec = sr.Recognizer()
    with sr.AudioFile(tmp_path) as source:
        audio = rec.record(source)

    try:
        os.remove(tmp_path)
    except Exception:
        pass
    return audio


def main():
    test_phrases = [
        ("Abra o bloco de notas", ["bloco", "notas"]),
        ("Abra o Google Chrome", ["google", "chrome"]),
        ("Abra o Google Chrome", ["google", "chrome"]),
        ("Abra o bloco de notas", ["bloco", "notas"]),
        ("Abra a pasta downloads", ["pasta", "downloads"]),
        ("Pesquise por inteligência artificial", ["inteligência", "artificial"]),
        ("Abra o bloco de notas agora", ["bloco", "notas", "agora"]),
        ("KON, você pode abrir o Google Chrome para mim?", ["google", "chrome"]),
        ("Abra a calculadora", ["calculadora"]),
        ("Pesquise por notícias sobre inteligência artificial", ["notícias", "inteligência", "artificial"]),
    ]

    engine = SpeechRecognitionEngine(
        language="pt-BR",
        pause_threshold=1.3,
        non_speaking_duration=0.8,
        energy_threshold=350.0,
        phrase_time_limit=12,
    )

    print("=" * 80)
    print("      TESTE BUG 1 — VALIDAÇÃO DE NÃO-CORTE DE FINAL DE PALAVRAS/FRASES")
    print("=" * 80)
    print(f"{'#':<3} | {'Frase Original':<40} | {'Texto Reconhecido':<30} | {'Status'}")
    print("-" * 80)

    results = []
    for idx, (phrase, required_words) in enumerate(test_phrases, 1):
        audio = synthesize_phrase(phrase)
        t0 = time.perf_counter()
        recognized = engine.transcribe(audio, language="pt-BR")
        lat = time.perf_counter() - t0

        # Check that trailing words are NOT truncated
        missing = [w for w in required_words if w.lower() not in recognized.lower()]
        passed = len(missing) == 0 and len(recognized.strip()) > 0

        status = "PASS (Completo)" if passed else f"FAIL (Faltou: {missing})"
        results.append({"num": idx, "phrase": phrase, "recognized": recognized, "passed": passed, "lat": lat})
        print(f"{idx:<3} | {phrase:<40} | {recognized:<30} | {status}")

    print("-" * 80)
    passed_count = sum(1 for r in results if r["passed"])
    print(f"Resultado final: {passed_count}/{len(test_phrases)} frases completas sem corte.")
    print("=" * 80)


if __name__ == "__main__":
    main()
