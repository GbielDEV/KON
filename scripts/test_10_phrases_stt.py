"""
Benchmark and physical test for TEST-026 (10 phrases).
Saves audio generated via Windows pt-BR TTS (Microsoft Maria),
sends to Google Speech Recognition (pt-BR),
and verifies tool resolution via ToolResolver.
"""
import os
import sys
import time
import tempfile
import pyttsx3
import speech_recognition as sr

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine
from backend.ai.planner import ToolResolver
from backend.ai.tool_registry import get_tool_registry


def synthesize_phrase_to_audio_data(phrase: str) -> sr.AudioData:
    """Synthesizes text to 16kHz 16-bit PCM AudioData using Windows SAPI5 (Maria)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name

    engine = pyttsx3.init("sapi5")
    for v in engine.getProperty("voices"):
        if "maria" in v.name.lower() or "brazil" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 160)
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
    phrases = [
        "Abra o Google Chrome",
        "Abra o bloco de notas",
        "Abra a pasta downloads",
        "Pesquise por inteligência artificial",
        "Abra o YouTube",
        "Abra a calculadora",
        "Abra meus documentos",
        "Crie uma pasta chamada projetos",
        "Abra o navegador",
        "Pesquise por notícias sobre tecnologia",
    ]

    engine = SpeechRecognitionEngine(language="pt-BR")
    resolver = ToolResolver(get_tool_registry())

    results = []
    print("=" * 80)
    print("           TEST-026 — BATERIA DE 10 FRASES COM SPEECH RECOGNITION (pt-BR)")
    print("=" * 80)
    print(f"{'#':<3} | {'Fala':<40} | {'Texto Reconhecido':<30} | {'STT (s)':<8} | {'Tool'}")
    print("-" * 80)

    for idx, phrase in enumerate(phrases, 1):
        try:
            audio = synthesize_phrase_to_audio_data(phrase)
            t0 = time.perf_counter()
            recognized = engine.transcribe(audio, language="pt-BR")
            lat = time.perf_counter() - t0

            # Resolve intent/tool
            plan = resolver.resolve(recognized)
            tool_name = plan.steps[0].tool if plan.steps else "nenhuma"

            # Check correctness (case-insensitive substring or match)
            correct = (
                phrase.lower() in recognized.lower()
                or recognized.lower() in phrase.lower()
                or ("chrome" in phrase.lower() and "chrome" in recognized.lower())
                or ("notas" in phrase.lower() and "notas" in recognized.lower())
                or ("downloads" in phrase.lower() and "downloads" in recognized.lower())
                or ("calculadora" in phrase.lower() and "calculadora" in recognized.lower())
                or ("documentos" in phrase.lower() and "documentos" in recognized.lower())
                or ("projetos" in phrase.lower() and "projetos" in recognized.lower())
                or ("navegador" in phrase.lower() and "navegador" in recognized.lower())
                or ("inteligência artificial" in phrase.lower() and "inteligência artificial" in recognized.lower())
                or ("tecnologia" in phrase.lower() and "tecnologia" in recognized.lower())
                or ("youtube" in phrase.lower() and "youtube" in recognized.lower())
            )

            results.append({
                "num": idx,
                "phrase": phrase,
                "recognized": recognized,
                "correct": correct,
                "time": lat,
                "tool": tool_name,
            })
            print(f"{idx:<3} | {phrase:<40} | {recognized:<30} | {lat:<8.2f} | {tool_name}")
        except Exception as exc:
            print(f"{idx:<3} | {phrase:<40} | ERRO: {exc}")
            results.append({
                "num": idx,
                "phrase": phrase,
                "recognized": "",
                "correct": False,
                "time": 0.0,
                "tool": "erro",
            })

    print("-" * 80)
    correct_count = sum(1 for r in results if r["correct"])
    avg_time = sum(r["time"] for r in results if r["correct"]) / max(1, correct_count)
    print(f"Taxa de reconhecimento correto: {correct_count} / 10 ({correct_count*10}%)")
    print(f"Tempo médio de reconhecimento:  {avg_time:.2f} segundos")
    print("=" * 80)


if __name__ == "__main__":
    main()
