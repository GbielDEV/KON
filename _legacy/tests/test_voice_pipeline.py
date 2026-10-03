"""
Automated unit and integration tests for Marco 2 Voice Pipeline.
"""
import asyncio
from backend.core.state import AssistantState
from backend.core.events import EventBus
from backend.core.kon import KONCore
from backend.voice.microphone import MicrophoneService
from backend.voice.text_to_speech import WindowsTTS
from backend.voice.wakeword import MockWakeWordDetector
from backend.ai.brain import DeterministicCommandParser
from backend.computer.applications import ApplicationManager


def test_microphone_service_detection():
    mic = MicrophoneService()
    name = mic.get_device_name()
    assert isinstance(name, str)
    assert len(name) > 0


def test_deterministic_command_parser():
    parser = DeterministicCommandParser()

    phrases = [
        "abra o google chrome",
        "abra o chrome",
        "abrir o google chrome",
        "inicie o chrome",
        "abre o chrome",
    ]

    for phrase in phrases:
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(parser.process_intent(phrase))
        loop.close()
        assert res["intent"] == "open_application", f"Failed for phrase: '{phrase}'"
        assert res["application"] == "chrome"
        assert res["response_text"] == "Abrindo o Google Chrome."

    # Test other applications (Notepad, Calc)
    loop = asyncio.new_event_loop()
    res_notepad = loop.run_until_complete(parser.process_intent("abra o bloco de notas"))
    assert res_notepad["intent"] == "open_application"
    assert res_notepad["application"] == "notepad"

    res_calc = loop.run_until_complete(parser.process_intent("abra a calculadora"))
    assert res_calc["intent"] == "open_application"
    assert res_calc["application"] == "calc"

    # Test folder intents
    res_downloads = loop.run_until_complete(parser.process_intent("abra a pasta downloads"))
    assert res_downloads["intent"] == "open_folder"
    assert res_downloads["folder"] == "Downloads"
    assert res_downloads["response_text"] == "Abrindo a pasta Downloads."

    res_docs = loop.run_until_complete(parser.process_intent("abrir documentos"))
    assert res_docs["intent"] == "open_folder"
    assert res_docs["folder"] == "Documents"

    # Test system status
    res_status = loop.run_until_complete(parser.process_intent("status do sistema"))
    assert res_status["intent"] == "system_status"

    # Test greeting
    res_greeting = loop.run_until_complete(parser.process_intent("Olá KON"))
    loop.close()
    assert res_greeting["intent"] == "greeting"


def test_safe_application_manager():
    # Chrome must be recognized as an authorized application
    assert "chrome" in ApplicationManager.ALLOWED_APPLICATIONS

    # Unauthorized apps must be strictly rejected
    res_bad = ApplicationManager.open_application("malicious_app_name")
    assert res_bad["success"] is False
    assert res_bad["error"] == "UNAUTHORIZED_OR_UNKNOWN_APPLICATION"

    # Chrome path resolution
    chrome_path = ApplicationManager.resolve_application_path("chrome")
    assert chrome_path is not None, "Chrome executable path should be resolved on Windows"
    assert chrome_path.exists()
    assert "chrome.exe" in str(chrome_path).lower()


def test_wake_word_mock_detector():
    detector = MockWakeWordDetector(wake_word="Okay KON")
    triggered = []

    detector.start(callback=lambda: triggered.append(True))
    assert detector.is_active() is True

    detector.trigger_mock()
    assert len(triggered) == 1

    detector.stop()
    assert detector.is_active() is False


def test_tts_worker_thread():
    bus = EventBus()
    tts = WindowsTTS(event_bus=bus)
    completed = []

    tts.speak("Teste unitario", on_complete=lambda: completed.append(True))

    # Give worker thread up to 6.0s to initialize COM and complete synthesis
    import time
    t0 = time.time()
    while not completed and time.time() - t0 < 6.0:
        time.sleep(0.1)

    assert len(completed) == 1
    tts.stop()


def test_full_mock_voice_cycle():
    core = KONCore(test_mode=True)
    # KONCore starts in BOOT state until start() is called and preload completes
    assert core.state == AssistantState.BOOT

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        core.run_voice_cycle(mock_command_text="Abra o Google Chrome")
    )
    loop.close()

    assert result["success"] is True
    assert result["intent"]["intent"] in ("open_application", "abrir_navegador")
    assert core.state == AssistantState.IDLE

    # Verify command was logged in database
    history = core.memory.get_recent_history(limit=1)
    assert len(history) > 0
    assert "chrome" in history[0]["command"].lower()


def test_full_mock_voice_cycle_folder():
    core = KONCore(test_mode=True)
    # KONCore starts in BOOT state until start() is called and preload completes
    assert core.state == AssistantState.BOOT

    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        core.run_voice_cycle(mock_command_text="Abra a pasta downloads")
    )
    loop.close()

    assert result["success"] is True
    assert result["intent"]["intent"] in ("open_folder", "abrir_pasta")
    assert core.state == AssistantState.IDLE
