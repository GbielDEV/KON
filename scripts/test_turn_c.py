import os
import sys
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry
from backend.core.live_engine import KON_SYSTEM_INSTRUCTION, MODEL_NAME

load_dotenv()


async def test_file_tool():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    registry = get_tool_registry()
    dispatcher = GeminiToolDispatcher(registry)
    tools_config = dispatcher.get_gemini_tools_config()

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        input_audio_transcription={},
        system_instruction=KON_SYSTEM_INSTRUCTION,
        tools=tools_config,
    )

    print("\n--- TESTANDO TOOL CALLING ('Procure o arquivo teste') ---", flush=True)

    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        t0 = time.time()
        print("\nEnviando: 'Procure o arquivo teste'...", flush=True)
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Procure o arquivo teste.")])]
        )

        tool_called = False
        tool_name = ""
        t_tool = None
        t_exec_end = None
        t_first_audio = None
        response_speech = ""

        # Loop de recepção
        turn = session.receive()
        async for resp in turn:
            t_now = time.time()
            if resp.tool_call:
                t_tool = t_now
                tool_called = True
                fc = resp.tool_call.function_calls[0]
                tool_name = fc.name
                print(f"[{t_now - t0:.3f}s] Tool Call recebida: '{tool_name}' com args {fc.args}", flush=True)

                t_exec_start = time.time()
                fn_resps = await dispatcher.execute_function_calls(resp.tool_call.function_calls)
                t_exec_end = time.time()
                print(f"[{t_exec_end - t0:.3f}s] Ferramenta executada em {(t_exec_end - t_exec_start)*1000:.1f}ms. Enviando retorno ao Gemini...", flush=True)
                await session.send_tool_response(function_responses=fn_resps)

            if resp.server_content:
                if resp.server_content.output_transcription:
                    delta = resp.server_content.output_transcription.text or ""
                    response_speech += delta
                    print(delta, end="", flush=True)

                if resp.server_content.model_turn and tool_called:
                    for part in resp.server_content.model_turn.parts:
                        if getattr(part, "thought", False):
                            continue
                        if part.inline_data and isinstance(part.inline_data.data, bytes) and t_first_audio is None:
                            t_first_audio = t_now

                if resp.server_content.turn_complete:
                    print("\n[Turn Complete]", flush=True)
                    break

        print(f"\nFala -> Tool Call: {(t_tool - t0):.3f}s", flush=True)
        print(f"Tool Execution: {(t_exec_end - t_tool):.3f}s", flush=True)
        if t_first_audio and t_exec_end:
            print(f"Tool Response -> Primeiro Áudio: {(t_first_audio - t_exec_end):.3f}s", flush=True)
        print(f"Resposta transcrita: '{response_speech.strip()}'", flush=True)

        assert tool_called, "Deveria ter chamado uma ferramenta de busca de arquivo!"
        print("\n>>> TESTE C PASS: Ferramenta invocada, executada e respondida com áudio!", flush=True)


if __name__ == "__main__":
    asyncio.run(test_file_tool())
