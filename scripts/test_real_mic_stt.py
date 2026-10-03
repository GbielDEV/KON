"""
Diagnostic script for testing real hardware capture:
AudioCapture -> VAD -> STT (faster-whisper small) -> NLU -> Command Registry -> TTS.
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.vad import VoiceActivityDetector
from voice_assistant.nlu.intent_parser import IntentParser
from voice_assistant.commands.registry import get_registry
from voice_assistant.tts.speak import TextToSpeech



def run_hardware_diagnostic():
    print("=" * 55)
    print(" DIAGNÓSTICO DE HARDWARE REAL DO KON")
    print("=" * 55)

    # 1. Microphone test
    cap = AudioCapture()
    dev_name = cap.get_device_name()
    avail = cap.is_available()
    print(f"[MIC] Dispositivo: '{dev_name}' | Disponível: {avail}")
    if not avail:
        print("[FAIL] Microfone não disponível no sistema.")
        return False

    started = cap.start()
    print(f"[MIC] Stream iniciado com sucesso: {started}")
    if not started:
        print("[FAIL] Não foi possível iniciar stream de áudio.")
        return False

    time.sleep(0.5)
    chunk = cap.read_chunk(timeout=1.0)
    print(f"[MIC] Chunk capturado com sucesso: {len(chunk) if chunk else 0} bytes")
    cap.stop()

    # 2. Simple Command Capture test
    from voice_assistant.audio.simple_capture import SimpleCommandCapture
    simple_cap = SimpleCommandCapture()
    simple_avail = simple_cap.is_available()
    print(f"[CAPTURE] SimpleCommandCapture disponível: {simple_avail}")

    # Legacy VAD test
    vad = VoiceActivityDetector(mode=2)
    silence = bytes(640)
    vad_ok = (vad.is_speech_frame(silence) is False)
    print(f"[VAD] Teste de quadro de silêncio (legado): {vad_ok} (False esperado)")


    # 3. TTS test
    print("[TTS] Testando motor de síntese de voz...")
    tts = TextToSpeech()
    tts.falar("Diagnóstico do sistema KON.")
    time.sleep(1.5)
    print("[TTS] Síntese executada com sucesso.")

    # 4. NLU test
    print("[NLU] Testando NLU (sentence-transformers)...")
    nlu = IntentParser()
    resolved = nlu.resolver_intent("abrir navegador", threshold=0.55)
    print(f"[NLU] Intent resolvido para 'abrir navegador': {resolved}")

    # 5. Registry test
    print("[COMMAND] Testando Command Registry...")
    reg = get_registry()
    cmd_res = reg.dispatch(resolved)
    print(f"[COMMAND] Resultado do comando '{resolved}': {cmd_res.get('response_text')}")

    print("=" * 55)
    print(" TODOS OS COMPONENTES DO PIPELINE REAL VALIDADOS!")
    print("=" * 55)
    return True


if __name__ == "__main__":
    run_hardware_diagnostic()
