"""
Teste Direto e Interativo de Voz do KON (Marco 2.1).
Permite testar o pipeline completo de voz de forma simples, visual e direta:
- Microfone Real com medidor de volume (VU meter) em tempo real
- Detecção da wake word "Okay KON" (ou "Jarvis" / "Alexa")
- Áudio real no alto-falante: "Sim?" (Microsoft Maria pt-BR)
- Captura inteligente de comando com VAD (1.5s de silêncio)
- Transcrição STT (SpeechRecognition pt-BR)
- Resolução de Comandos e Ferramentas (ToolResolver)
- Ação real (abertura de navegador, relógio, etc.)
- Confirmação falada e retorno a IDLE
- Opção de pressionar [ENTER] a qualquer momento para testar o comando diretamente!
"""
import sys
import os
import time
import threading
import msvcrt
import numpy as np

# Set project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from voice_assistant.core.state_machine import VoicePipelineOrchestrator

def print_banner():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 70)
    print("       KON — ASSISTENTE DE VOZ GERAL & EXECUÇÃO DE FERRAMENTAS")
    print("=" * 70)


def main():
    print_banner()
    print("[1/3] Inicializando subsistemas (PyAudio, SpeechRecognition pt-BR, ToolRegistry)...")

    # 1. Start Orchestrator
    orchestrator = VoicePipelineOrchestrator()
    if not orchestrator.start():
        print("[ERRO] Não foi possível conectar ao microfone do computador.")
        input("Pressione Enter para fechar...")
        return

    mic_name = orchestrator.audio_capture.get_device_name()
    print(f"[2/3] Microfone conectado: '{mic_name}' @ 16kHz mono")
    print("[3/3] Voz conectada: 'Microsoft Maria Desktop - Portuguese(Brazil)'")

    print("\n" + "=" * 70)
    print("  STATUS: PRONTO E ESCUTANDO (Pipeline Geral Ativo)")
    print("=" * 70)
    print("  1. Diga em voz alta:  'Okay KON'  (ou 'Jarvis' / 'Alexa')")
    print("  2. Aguarde o beep/resposta falada: 'Sim?'")
    print("  3. Fale comandos naturais gerais, por exemplo:")
    print("     - 'Abra o Google Chrome'")
    print("     - 'Crie uma pasta chamada TesteKON na pasta Downloads'")
    print("     - 'Qual é o uso de memória do computador?'")
    print("     - 'Tire um print da tela'")
    print("     - 'Abra o Bloco de Notas e depois abra a pasta Documentos'")
    print("     - 'Pesquise cotação do dólar hoje no Google'")
    print("-" * 70)
    print("  [DICA]: Pressione [ESPAÇO] ou [ENTER] para ativar imediatamente!")
    print("  Pressione [Ctrl+C] a qualquer momento para sair.")
    print("=" * 70 + "\n")

    # Thread to listen for keyboard trigger (space or enter)
    def keyboard_trigger_listener():
        while orchestrator._is_running:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key in (b" ", b"\r", b"\n"):
                    if not orchestrator._is_cycle_active:
                        print("\n>>> [TECLADO] Gatilho manual acionado! Disparando ciclo de voz... <<<")
                        orchestrator.run_voice_cycle(wake_detected_at=time.time())
            time.sleep(0.05)

    kb_thread = threading.Thread(target=keyboard_trigger_listener, daemon=True)
    kb_thread.start()

    # Passive listener for real-time VU-meter (does NOT consume queue chunks)
    last_rms = [0.0]
    def on_audio_level(raw_bytes: bytes) -> None:
        if len(raw_bytes) >= 2560:
            samples = np.frombuffer(raw_bytes, dtype=np.int16)
            last_rms[0] = float(np.sqrt(np.mean(samples.astype(np.float32)**2)))

    orchestrator.audio_capture.add_listener(on_audio_level)

    # Main visual VU-meter loop
    try:
        while orchestrator._is_running:
            if orchestrator._is_cycle_active:
                time.sleep(0.2)
                continue

            rms = last_rms[0]
            # Recalibrated visual scale: silence (~50 RMS) -> 0 bars, normal speech (~950 RMS) -> 18/25 (72%), peak (~1300+ RMS) -> 25/25 (100%)
            # NOTE: This meter is purely visual telemetry and is NOT used as an audio gate for SpeechRecognition.
            bars = int(min(25, max(0, (rms - 50) / 50)))
            meter = "#" * bars + " " * (25 - bars)

            status_label = "FALANDO" if rms > 300 else "OUVINDO"
            sys.stdout.write(f"\rVolume Mic: [{meter}] ({status_label}) | Aguardando: 'Okay KON'...  ")
            sys.stdout.flush()

            time.sleep(0.08)

    except KeyboardInterrupt:
        print("\n\n[ENCERRANDO] Finalizando o assistente...")
    finally:
        orchestrator.audio_capture.remove_listener(on_audio_level)
        orchestrator.stop()
        print("[SUCESSO] Microfone e assistente finalizados.")


if __name__ == "__main__":
    main()
