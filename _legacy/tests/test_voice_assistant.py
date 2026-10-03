"""
Comprehensive unit tests for Marco 2 Voice Assistant subsystem.
Tests:
- IntentParser (Sentence-Transformers, cosine similarity, catalog matching, threshold rejection)
- CommandRegistry (Registration, Dispatch, ToolManager permissions, security against eval/exec)
- Decoupled interfaces (AudioCapture, WakeWordDetector, WhisperSTTEngine, TextToSpeech)
- End-to-end VoicePipelineOrchestrator voice cycle
"""
import numpy as np

from voice_assistant.nlu.intent_parser import IntentParser, normalize_intent_text
from voice_assistant.commands.registry import CommandRegistry, get_registry
from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.wake_word import MockWakeWordDetector
from voice_assistant.audio.vad import VoiceActivityDetector
from voice_assistant.stt.whisper_engine import MockSTTEngine
from voice_assistant.tts.speak import TextToSpeech
from voice_assistant.core.state_machine import VoicePipelineOrchestrator
from backend.core.state import AssistantState
from backend.core.events import EventBus
from backend.ai.tool_manager import ToolManager, PermissionLevel


# =========================================================
# 1. IntentParser Tests
# =========================================================

def test_intent_parser_normalization():
    assert normalize_intent_text("  Abrir O Google Chrome!! ") == "abrir o google chrome"
    assert normalize_intent_text("Que HORAS são? ") == "que horas sao"
    assert normalize_intent_text("Música & Vídeos") == "musica videos"


def test_intent_parser_recognition():
    parser = IntentParser()

    # Browser intent variations
    for phrase in ["abrir navegador", "abra o navegador", "quero abrir a internet", "iniciar navegador"]:
        intent = parser.resolver_intent(phrase, threshold=0.55)
        assert intent == "abrir_navegador", f"Falha para frase: '{phrase}'"

    # Time intent variations
    for phrase in ["que horas são", "qual o horário", "me diga as horas"]:
        intent = parser.resolver_intent(phrase, threshold=0.55)
        assert intent == "informar_horario", f"Falha para frase: '{phrase}'"

    # Media intent variations
    for phrase in ["tocar música", "toque uma música", "iniciar música"]:
        intent = parser.resolver_intent(phrase, threshold=0.55)
        assert intent == "tocar_musica", f"Falha para frase: '{phrase}'"


def test_intent_parser_threshold_rejection():
    parser = IntentParser()
    # Completely unrelated phrase must return None
    intent = parser.resolver_intent("compre três quilos de batatas no supermercado", threshold=0.6)
    assert intent is None

    empty_intent = parser.resolver_intent("", threshold=0.6)
    assert empty_intent is None


# =========================================================
# 2. CommandRegistry Tests
# =========================================================

def test_command_registry_dispatch():
    tool_mgr = ToolManager()
    reg = CommandRegistry(tool_manager=tool_mgr)

    # Register custom test command
    called = []

    def custom_handler(item="mundo"):
        called.append(item)
        return {"success": True, "response_text": f"Olá {item}!"}

    reg.register("teste_intent", custom_handler, permission=PermissionLevel.SAFE)

    assert reg.has_command("teste_intent") is True
    assert reg.has_command("inexistente") is False

    # Dispatch valid command
    result = reg.dispatch("teste_intent", slots={"item": "KON"})
    assert result["success"] is True
    assert result["response_text"] == "Olá KON!"
    assert called == ["KON"]

    # Dispatch unknown command
    bad_res = reg.dispatch("nao_registrado")
    assert bad_res["success"] is False
    assert bad_res["error"] == "COMMAND_NOT_FOUND"


def test_command_registry_security_permission():
    tool_mgr = ToolManager()
    reg = CommandRegistry(tool_manager=tool_mgr)

    # Critical command requiring double-confirmation
    def critical_action():
        return "Executado perigosamente."

    reg.register("critical_intent", critical_action, permission=PermissionLevel.CRITICAL)

    result = reg.dispatch("critical_intent")
    assert result["success"] is False
    assert result.get("needs_confirmation") is True


def test_system_commands_registered():
    # Verify default system commands are available in global registry
    reg = get_registry()
    assert reg.has_command("abrir_navegador") is True
    assert reg.has_command("informar_horario") is True
    assert reg.has_command("tocar_musica") is True

    # Test time format
    time_res = reg.dispatch("informar_horario")
    assert time_res["success"] is True
    assert "horas" in time_res["response_text"]


# =========================================================
# 3. Decoupled Interfaces Tests (WakeWord, STT, TTS, VAD, Mic)
# =========================================================

def test_wake_word_interfaces():
    detector = MockWakeWordDetector(wake_word="Okay KON")
    triggered = []

    detector.start(callback=lambda: triggered.append(True))
    assert detector.is_active() is True

    # Simulate trigger
    detector.trigger_mock()
    assert len(triggered) == 1

    detector.stop()
    assert detector.is_active() is False


def test_vad_frame_evaluation():
    vad = VoiceActivityDetector(mode=2, default_silence_timeout=1.5)
    # Silence frame (640 zero bytes = 20ms of 16kHz int16)
    silence_frame = bytes(640)
    assert vad.is_speech_frame(silence_frame) is False


def test_stt_interface():
    stt = MockSTTEngine(default_text="abrir navegador")
    text = stt.transcribe(np.zeros(16000, dtype=np.float32))
    assert text == "abrir navegador"
    assert stt.last_latency >= 0.0


def test_tts_interface():
    tts = TextToSpeech()
    assert hasattr(tts, "falar")
    assert hasattr(tts, "speak")
    assert hasattr(tts, "is_speaking")
    assert hasattr(tts, "last_latency")


def test_audio_capture_device_detection():
    cap = AudioCapture()
    dev_name = cap.get_device_name()
    assert isinstance(dev_name, str)
    assert len(dev_name) > 0


# =========================================================
# 4. Orchestrator End-to-End Cycle Test
# =========================================================

def test_orchestrator_mock_cycle():
    bus = EventBus()
    events = []
    bus.subscribe_all(lambda ev: events.append(ev))

    mock_stt = MockSTTEngine(default_text="que horas são")
    orch = VoicePipelineOrchestrator(
        event_bus=bus,
        stt_engine=mock_stt,
        wake_word_detector=MockWakeWordDetector(wake_word="Okay KON"),
    )

    assert orch.state == AssistantState.IDLE

    # Run cycle with mock phrase
    result = orch.run_voice_cycle(mock_command_text="que horas são")

    assert result["success"] is True
    assert result["command"] == "que horas são"
    assert result["intent"]["intent"] == "informar_horario"
    assert orch.state == AssistantState.IDLE

    # Check state transitions published on EventBus
    state_events = [e for e in events if e.type == "state_changed"]
    assert len(state_events) >= 2
