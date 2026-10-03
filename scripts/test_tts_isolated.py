"""
Script de teste isolado do TTS para o Marco 2.1.
Verifica:
- Inicialização do pyttsx3 / SAPI5
- Seleção de voz (Microsoft Maria pt-BR)
- Áudio audível real no alto-falante
- Logs com timestamps de alta resolução
"""
import sys
import os
import time
import threading

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice_assistant.tts.speak import TextToSpeech

def main():
    print("=" * 50)
    print("TESTE ISOLADO DO TTS (VOZ REAL)")
    print("=" * 50)

    tts = TextToSpeech()
    print(f"[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] inicializado")

    done_event = threading.Event()
    t_end_audio = [None]

    def on_complete():
        t_end_audio[0] = time.time()
        print(f"[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] áudio finalizado")
        done_event.set()

    print(f"[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] falando: Sim?")
    t_req = time.time()
    tts.falar("Sim?", on_complete=on_complete)

    # Wait for completion
    success = done_event.wait(timeout=5.0)
    if success:
        print(f"[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] Sucesso na síntese. Latência total: {t_end_audio[0] - t_req:.3f}s")
    else:
        print("[TTS] ERRO: Timeout ao aguardar conclusão da síntese de áudio.")

    # Also test a longer phrase
    done_event.clear()
    print(f"\n[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] falando: Abrindo o navegador.")
    t_req2 = time.time()
    tts.falar("Abrindo o navegador.", on_complete=on_complete)
    success2 = done_event.wait(timeout=5.0)
    if success2:
        print(f"[{time.strftime('%H:%M:%S')}.{int((time.time()%1)*1000):03d}] [TTS] Sucesso na síntese. Latência total: {t_end_audio[0] - t_req2:.3f}s")
    else:
        print("[TTS] ERRO: Timeout na segunda síntese.")

if __name__ == "__main__":
    main()
