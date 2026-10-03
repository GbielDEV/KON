"""
Direct Real-Hardware Test for SimpleCommandCapture + Voice Pipeline.
Tests:
Wake word simulation or live input -> TTS "Sim?" -> SimpleCommandCapture -> Faster-Whisper STT -> NLU -> Command Execution -> TTS.
"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.simple_capture import SimpleCommandCapture
from voice_assistant.stt.whisper_engine import WhisperSTTEngine
from voice_assistant.nlu.intent_parser import IntentParser
from voice_assistant.commands.registry import get_registry
from voice_assistant.tts.speak import TextToSpeech


def test_real_capture_cycle():
    print("=" * 60)
    print("   TESTE DE CAPTURA REAL COM PyAudio (SIMPLIFICADA)")
    print("=" * 60)

    # 1. Initialize subsystems
    print("[1/4] Inicializando PyAudio, Whisper STT e NLU...")
    capture = SimpleCommandCapture(default_silence_threshold=400.0, default_max_duration=4.5)
    stt = WhisperSTTEngine(model_size="small", compute_type="int8")
    stt.preload()
    nlu = IntentParser()
    nlu.preload()
    reg = get_registry()
    tts = TextToSpeech()
    tts.preload()

    print(f"[2/4] Dispositivo de microfone: '{capture.get_device_name()}'")
    print("\n" + "=" * 60)
    print("  O teste começará agora.")
    print("  1. KON falará 'Sim?' no alto-falante.")
    print("  2. Em seguida, fale um comando (ex: 'Abra o navegador' ou 'Abra o bloco de notas').")
    print("=" * 60 + "\n")

    input("Pressione [ENTER] quando estiver pronto para falar...")

    # Simulated activation
    t_wake = time.time()
    print("\n[KON] 'Sim?'...")
    tts.falar("Sim?")
    time.sleep(0.3)  # Echo settle

    # Capture command
    t_cap_start = time.time()
    audio = capture.capture_command(
        max_duration=4.5,
        silence_threshold=400.0,
        silence_duration=1.0,
        min_duration=1.0,
        startup_timeout=3.5,
    )
    t_cap_end = time.time()
    cap_dur = t_cap_end - t_cap_start

    print(f"\n[OK] Áudio capturado: {len(audio)/16000:.2f}s (duração total da janela: {cap_dur:.2f}s)")

    if len(audio) == 0:
        print("[AVISO] Nenhum áudio capturado.")
        return

    # STT
    print("[STT] Transcrevendo com faster-whisper...")
    t_stt_start = time.time()
    text = stt.transcribe(audio, language="pt")
    t_stt_end = time.time()
    stt_dur = t_stt_end - t_stt_start
    print(f'[STT] Texto reconhecido: "{text}" ({stt_dur:.2f}s)')

    # NLU
    print("[NLU] Identificando intenção...")
    t_nlu_start = time.time()
    intent_res = nlu.get_intent_details(text, threshold=0.55)
    t_nlu_end = time.time()
    nlu_dur = (t_nlu_end - t_nlu_start) * 1000.0
    intent_name = intent_res.get("intent")
    print(f"[NLU] Intent: '{intent_name}' (confiança: {intent_res.get('confidence', 0):.2f}) ({nlu_dur:.1f}ms)")

    # Dispatch Command
    if intent_name and reg.has_command(intent_name):
        print(f"[ACTION] Executando comando '{intent_name}'...")
        res = reg.dispatch(intent_name, slots=intent_res.get("slots", {}))
        resp_speech = res.get("response_text", "Comando executado.")
        print(f"[ACTION] Sucesso: {res.get('success')} | Resposta: {resp_speech}")
        tts.falar(resp_speech)
        time.sleep(1.5)
    else:
        print(f"[ACTION] Nenhum comando associado ao intent '{intent_name}'.")

    t_total = time.time() - t_wake
    print("\n" + "=" * 60)
    print("               MÉTRICAS DO CICLO REAL")
    print("=" * 60)
    print(f" Tempo de captura simples: {cap_dur:.2f}s")
    print(f" Tempo Whisper STT:       {stt_dur:.2f}s")
    print(f" Tempo NLU:               {nlu_dur:.1f}ms")
    print(f" Texto reconhecido:       '{text}'")
    print(f" Intent:                  '{intent_name}'")
    print(f" Ciclo Total:             {t_total:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    test_real_capture_cycle()
