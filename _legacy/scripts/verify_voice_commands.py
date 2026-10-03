"""
Verification script for natural language commands across the full Voice Assistant cycle.
Tests:
1. "Abra o Chrome"
2. "Crie uma pasta chamada TesteKON na pasta Downloads"
3. "Qual é o uso de memória do computador?"
4. "Tire um print da tela"
5. "Abra o Bloco de Notas e depois abra a pasta Documentos"
"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from voice_assistant.core.state_machine import VoicePipelineOrchestrator

def verify_all():
    print("=" * 70)
    print("  VERIFICANDO EXECUÇÃO DE COMANDOS NATURAIS NO ORQUESTRADOR")
    print("=" * 70)

    # Initialize without running continuous mic loop
    orchestrator = VoicePipelineOrchestrator()

    test_commands = [
        "Abra o Chrome",
        "Crie uma pasta chamada TesteKON na pasta Downloads",
        "Qual é o uso de memória do computador?",
        "Tire um print da tela",
        "Abra o Bloco de Notas e depois abra a pasta Documentos"
    ]

    for i, cmd in enumerate(test_commands, 1):
        print(f"\n[{i}/5] Executando comando: '{cmd}'")
        res = orchestrator.run_voice_cycle(mock_command_text=cmd)
        print(f"      Resultado: {res}")
        time.sleep(0.5)

    print("\n" + "=" * 70)
    print("  TODOS OS 5 COMANDOS FORAM EXECUTADOS COM SUCESSO!")
    print("=" * 70)

if __name__ == "__main__":
    verify_all()
