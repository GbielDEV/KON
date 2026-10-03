"""
Test Multi-Tool execution and Context continuity with Gemini Live Tool Calling.
"""
import os
import asyncio
import pytest
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry

load_dotenv()


@pytest.mark.anyio
async def test_multi_tool_batch_execution():
    """Teste 10: Multi-tool — Executar lote com múltiplas ferramentas."""
    registry = get_tool_registry()
    dispatcher = GeminiToolDispatcher(registry=registry)

    # Simular lote com duas chamadas de ferramenta
    class MockCall1:
        id = "call_sys_1"
        name = "system_info"
        args = {"metric": "cpu"}

    class MockCall2:
        id = "call_app_2"
        name = "open_folder"
        args = {"folder": "Downloads"}

    responses = await dispatcher.execute_function_calls([MockCall1(), MockCall2()])
    assert len(responses) == 2

    assert responses[0].id == "call_sys_1"
    assert responses[0].name == "system_info"
    assert "cpu" in responses[0].response.get("result", "").lower() or "sucesso" in responses[0].response.get("result", "").lower()

    assert responses[1].id == "call_app_2"
    assert responses[1].name == "open_folder"
    assert "downloads" in responses[1].response.get("result", "").lower() or "sucesso" in responses[1].response.get("result", "").lower()
    print("  [OK] Multi-tool: Lote com system_info e open_folder executado com sucesso!")


@pytest.mark.anyio
async def test_contextual_tool_calling_e2e():
    """Teste 9: Contexto — Enviar pedido que aciona tool calling real via Gemini Live."""
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    model = "models/gemini-2.5-flash-native-audio-preview-12-2025"

    registry = get_tool_registry()
    dispatcher = GeminiToolDispatcher(registry=registry)
    tools_config = dispatcher.get_gemini_tools_config()

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=(
            "Você é o assistente KON. Se o usuário pedir para abrir a calculadora ou checar o sistema, "
            "use a ferramenta correspondente imediatamente."
        ),
        tools=tools_config
    )

    tool_called = False
    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send(input="KON, abra a calculadora por favor.", end_of_turn=True)

        try:
            async with asyncio.timeout(12.0):
                turn = session.receive()
                async for response in turn:
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            if fc.name in ("open_application", "calc"):
                                tool_called = True
                                # Responder ao Gemini
                                fn_resps = await dispatcher.execute_function_calls(response.tool_call.function_calls)
                                await session.send_tool_response(function_responses=fn_resps)
                                break
                    if tool_called:
                        break
        except asyncio.TimeoutError:
            pass

    assert tool_called, "O Gemini Live deveria ter acionado a ferramenta open_application via function calling!"
    print("  [OK] Contexto e Agente: Gemini Live interpretou o comando e acionou open_application autonomamente!")
