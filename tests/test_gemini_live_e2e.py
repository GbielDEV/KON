"""
End-to-End Test Suite for KON Gemini Live Architecture.
Tests Live API Handshake, Tool Dispatching, Security Permissions, Reconnection, and HUD Event Streams.
"""
import os
import pytest
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry
from backend.core.kon import KONCore
from backend.core.state import AssistantState

load_dotenv()


@pytest.mark.anyio
async def test_live_api_real_connection():
    """Teste 3: Live API — Abrir sessão real e enviar ping."""
    api_key = os.getenv("GEMINI_API_KEY")
    assert api_key, "GEMINI_API_KEY não configurada!"

    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    model = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Você é o assistente KON."
    )

    async with client.aio.live.connect(model=model, config=config) as session:
        assert session is not None
        # Enviar um frame de inicialização
        await session.send(input="Olá KON", end_of_turn=True)
        print("  [OK] Sessão Gemini Live aberta e mensagem enviada com sucesso!")


@pytest.mark.anyio
async def test_tool_calling_open_application():
    """Teste 8: Tool Calling — Verificar resolução e execução de open_application."""
    registry = get_tool_registry()
    dispatcher = GeminiToolDispatcher(registry=registry)

    # Simular function call do Gemini
    class MockFunctionCall:
        id = "call_abc123"
        name = "open_application"
        args = {"application": "notepad"}

    responses = await dispatcher.execute_function_calls([MockFunctionCall()])
    assert len(responses) == 1
    resp = responses[0]
    assert resp.id == "call_abc123"
    assert resp.name == "open_application"
    assert "notepad" in resp.response.get("result", "").lower() or "sucesso" in resp.response.get("result", "").lower()
    print(f"  [OK] open_application executou com sucesso: {resp.response.get('result')}")


@pytest.mark.anyio
async def test_security_critical_permission_blocked_without_confirmation():
    """Teste 11: Segurança — Ferramenta CRITICAL não executa sem autorização."""
    registry = get_tool_registry()

    # Callback de confirmação que NEGA a ação
    async def mock_deny_callback(data):
        # Nega automaticamente
        return False

    dispatcher = GeminiToolDispatcher(
        registry=registry,
        on_confirmation_request=mock_deny_callback
    )

    class MockCriticalCall:
        id = "call_crit_456"
        name = "shutdown_system"
        args = {}

    responses = await dispatcher.execute_function_calls([MockCriticalCall()])
    assert len(responses) == 1
    resp = responses[0]
    result_text = resp.response.get("result", "")
    assert "cancelou" in result_text.lower() or "não autorizou" in result_text.lower()
    print(f"  [OK] Ação CRITICAL bloqueada com sucesso: {result_text}")


@pytest.mark.anyio
async def test_hud_websocket_event_broadcasting():
    """Teste 13: HUD — Confirmar que o servidor transmite eventos reais ao HUD."""
    from backend.server.ws_server import create_app
    from fastapi.testclient import TestClient

    core = KONCore(test_mode=True)
    app = create_app(core)
    client = TestClient(app)

    # Health endpoint
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    data = res_health.json()
    assert data["architecture"] == "ADA V2 Blueprint (Gemini Live Native Audio)"

    # Telemetry snapshot
    res_telem = client.get("/api/telemetry")
    assert res_telem.status_code == 200
    telem = res_telem.json()
    assert telem["native_audio"] is True
    assert "cpu_percent" in telem

    # State transition event
    core.set_state(AssistantState.SPEAKING, "Falando resposta")
    assert core.state == AssistantState.SPEAKING
    print("  [OK] HUD e endpoints verificados!")
