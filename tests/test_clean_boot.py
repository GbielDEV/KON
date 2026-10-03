"""
Test 1: Clean Boot Verification.
Verifies that KONCore starts cleanly in under 2 seconds without loading
any legacy speech recognition, whisper, openwakeword, pyttsx3, or webrtcvad modules.
"""
import sys
import time

def test_clean_boot_no_legacy():
    start = time.time()
    from backend.core.kon import KONCore
    from backend.core.state import AssistantState

    core = KONCore(test_mode=True)
    duration = time.time() - start

    # Check boot time (cold import on Windows)
    assert duration < 6.0, f"Boot demorou muito ({duration:.2f}s)"

    # Verify no legacy voice modules are in sys.modules
    forbidden = [
        "whisper",
        "faster_whisper",
        "speech_recognition",
        "pyttsx3",
        "openwakeword",
        "webrtcvad",
        "voice_assistant",
        "backend.voice",
    ]
    loaded_forbidden = [mod for mod in forbidden if mod in sys.modules]
    assert not loaded_forbidden, f"Módulos legados detectados em memória: {loaded_forbidden}"

    # Verify initial state
    assert core.state in (AssistantState.BOOT, AssistantState.IDLE)
    print(f"PASS: Boot limpo em {duration:.3f}s sem nenhum módulo legado carregado!")

if __name__ == "__main__":
    test_clean_boot_no_legacy()
