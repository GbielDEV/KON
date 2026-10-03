"""
Standalone Physical Test for SpeechRecognition in KON (Section 15).
Runs directly with the REAL physical microphone and PyAudio:
1. Lists all audio input devices.
2. Selects the configured microphone (identifying Realtek Audio or default).
3. Opens the real device and calibrates ambient noise.
4. Prompts the user to speak naturally.
5. Captures speech and sends to Google Speech Recognition (pt-BR).
6. Displays recognized text, listen time, recognition latency, and total round-trip.
7. Repeats 3 times and reports averages.
"""
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import speech_recognition as sr

from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine


def main():
    print("=" * 65)
    print("      KON — TESTE STANDALONE DE RECONHECIMENTO DE VOZ FÍSICO")
    print("=" * 65)

    # 1. List microphones
    print("\n[1/4] Listando microfones disponíveis no computador:")
    names = sr.Microphone.list_microphone_names()
    for idx, name in enumerate(names):
        marker = " <--- SELECIONADO" if "realtek" in name.lower() and "input" in name.lower() or "microfone" in name.lower() and idx == 1 else ""
        print(f"  [{idx:2d}] {name}{marker}")

    # 2. Instantiate Engine
    print("\n[2/4] Inicializando SpeechRecognitionEngine...")
    engine = SpeechRecognitionEngine(
        language="pt-BR",
        device_name="Microfone (Realtek(R) Audio)",
        timeout=6,
        phrase_time_limit=8,
        recognition_timeout=10,
    )
    selected_idx = engine.device_index
    selected_name = names[selected_idx] if selected_idx is not None and selected_idx < len(names) else "Padrão do Windows"
    print(f"  -> Dispositivo ativo: Índice {selected_idx} ('{selected_name}')")

    # 3. Calibrate
    print("\n[3/4] Calibrando ruído ambiente...")
    engine.calibrate_ambient_noise(duration=0.8)

    # 4. Interactive 3-cycle test
    print("\n[4/4] Iniciando bateria de 3 testes com o MICROFONE REAL.")
    print("Sugestões de frases para falar em cada rodada:")
    print("  1. 'Abra o Google Chrome'")
    print("  2. 'Abra o bloco de notas'")
    print("  3. 'Pesquise por inteligência artificial'")
    print("-" * 65)

    results = []

    for round_num in range(1, 4):
        print(f"\n>>> RODADA {round_num} DE 3 <<<")
        print("Fale agora no microfone...")

        t_cycle_start = time.perf_counter()
        text = engine.listen_and_transcribe(timeout=6, phrase_time_limit=8)
        t_cycle_end = time.perf_counter()

        t_listen = engine.last_listen_duration
        t_rec = engine.last_recognition_latency
        t_total = t_cycle_end - t_cycle_start

        if text:
            print("  [RESULTADO]: SUCESSO")
            print(f"  -> Texto reconhecido: '{text}'")
            print(f"  -> Tempo de escuta:    {t_listen:.2f}s")
            print(f"  -> Tempo reconhecimento (Google): {t_rec:.2f}s")
            print(f"  -> Tempo total da rodada:         {t_total:.2f}s")
            results.append({"round": round_num, "text": text, "success": True, "time": t_total, "rec_time": t_rec})
        else:
            print("  [RESULTADO]: NENHUMA FALA RECONHECIDA OU TIMEOUT")
            print(f"  -> Tempo decorrido: {t_total:.2f}s")
            results.append({"round": round_num, "text": "", "success": False, "time": t_total, "rec_time": 0.0})

        if round_num < 3:
            time.sleep(1.0)

    print("\n" + "=" * 65)
    print("                   RESUMO DO TESTE STANDALONE")
    print("=" * 65)
    successes = sum(1 for r in results if r["success"])
    print(f"Sucesso: {successes}/3 rodadas")
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        print(f"  Rodada {r['round']}: [{status}] '{r['text']}' (total: {r['time']:.2f}s, STT: {r['rec_time']:.2f}s)")

    if successes > 0:
        avg_rec = sum(r["rec_time"] for r in results if r["success"]) / successes
        print(f"\nTempo médio de reconhecimento via Google pt-BR: {avg_rec:.2f}s")
    print("=" * 65)


if __name__ == "__main__":
    main()
