"""
Bateria Completa de Testes Reais do KON:
Teste A — Fala sem wake word ("Olá, tudo bem?")
Teste B — Comando sem wake word ("Abra o Google Chrome.")
Teste C — Ferramenta ("Procure o arquivo teste.")
Teste D — Conversa contínua multi-turn (3 turnos com contexto)
Teste E — Interrupção / Barge-in
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry
from backend.core.live_engine import KON_SYSTEM_INSTRUCTION, MODEL_NAME

load_dotenv()


async def run_test_suite():
    api_key = os.getenv("GEMINI_API_KEY")
    assert api_key, "GEMINI_API_KEY necessária!"

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

    results = {}
    latencies = {}

    print("=" * 70)
    print("       BATERIA DE VALIDAÇÃO REAL DO KON (ADA V2 / GEMINI LIVE)")
    print("=" * 70)

    # -------------------------------------------------------------
    # TESTE A: Fala sem wake word ("Olá, tudo bem?")
    # -------------------------------------------------------------
    print("\n>>> EXECUTANDO TESTE A: Conversação Direta Sem Wake Word...")
    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        t0 = time.time()
        # Enviar fala direta sem mencionar 'Okay KON'
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Olá, tudo bem?")])]
        )

        first_audio = False
        response_text = ""
        t_first_resp = None
        t_first_audio = None

        turn = session.receive()
        async for resp in turn:
            t_curr = time.time()
            if resp.server_content:
                if t_first_resp is None:
                    t_first_resp = t_curr

                if resp.server_content.output_transcription:
                    delta = resp.server_content.output_transcription.text or ""
                    response_text += delta

                if resp.server_content.model_turn:
                    for part in resp.server_content.model_turn.parts:
                        if getattr(part, "thought", False):
                            continue
                        if part.inline_data and isinstance(part.inline_data.data, bytes):
                            if not first_audio:
                                first_audio = True
                                t_first_audio = t_curr

                if resp.server_content.turn_complete:
                    break

        latencies["fala_para_primeira_resposta"] = (t_first_resp - t0) if t_first_resp else 0
        latencies["fala_para_primeiro_audio"] = (t_first_audio - t0) if t_first_audio else 0

        passed_a = first_audio and len(response_text.strip()) > 0
        results["Teste A (Fala direta sem wake word)"] = "PASS" if passed_a else "FAIL"
        print(f"  [RESULTADO TESTE A] {'PASS' if passed_a else 'FAIL'}")
        print(f"  • Resposta recebida: '{response_text.strip()}'")
        print(f"  • Fala -> 1ª Resposta: {latencies['fala_para_primeira_resposta']*1000:.1f}ms")
        print(f"  • Fala -> 1º Áudio: {latencies['fala_para_primeiro_audio']*1000:.1f}ms")

    # -------------------------------------------------------------
    # TESTE B: Comando sem wake word ("Abra o Google Chrome")
    # -------------------------------------------------------------
    print("\n>>> EXECUTANDO TESTE B: Comando sem Wake Word (open_application)...")
    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        t0 = time.time()
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Abra o Google Chrome.")])]
        )

        tool_called = False
        called_tools = []
        t_tool_call = None
        t_exec_start = None
        t_exec_end = None
        t_post_tool_audio = None

        turn = session.receive()
        async for resp in turn:
            t_curr = time.time()
            if resp.tool_call:
                t_tool_call = t_curr
                tool_called = True
                called_tools = [fc.name for fc in resp.tool_call.function_calls]
                print(f"  • Tool Call recebida: {called_tools}")

                t_exec_start = time.time()
                fn_resps = await dispatcher.execute_function_calls(resp.tool_call.function_calls)
                t_exec_end = time.time()

                await session.send_tool_response(function_responses=fn_resps)

            if resp.server_content and resp.server_content.model_turn and tool_called:
                for part in resp.server_content.model_turn.parts:
                    if getattr(part, "thought", False):
                        continue
                    if part.inline_data and isinstance(part.inline_data.data, bytes) and t_post_tool_audio is None:
                        t_post_tool_audio = t_curr

            if resp.server_content and resp.server_content.turn_complete:
                break

        latencies["fala_para_function_call"] = (t_tool_call - t0) if t_tool_call else 0
        latencies["tool_execution_time"] = (t_exec_end - t_exec_start) if (t_exec_start and t_exec_end) else 0
        latencies["tool_para_audio_gemini"] = (t_post_tool_audio - t_exec_end) if (t_post_tool_audio and t_exec_end) else 0

        passed_b = "open_application" in called_tools
        results["Teste B (Comando sem wake word)"] = "PASS" if passed_b else "FAIL"
        print(f"  [RESULTADO TESTE B] {'PASS' if passed_b else 'FAIL'}")
        print(f"  • Fala -> Function Call: {latencies['fala_para_function_call']*1000:.1f}ms")
        print(f"  • Execução da Ferramenta: {latencies['tool_execution_time']*1000:.1f}ms")
        print(f"  • Tool Response -> Áudio do Gemini: {latencies['tool_para_audio_gemini']*1000:.1f}ms")

    # -------------------------------------------------------------
    # TESTE C: Ferramenta de Arquivo ("Procure o arquivo teste")
    # -------------------------------------------------------------
    print("\n>>> EXECUTANDO TESTE C: Ferramenta de Arquivo ('Procure o arquivo teste')...")
    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        t0 = time.time()
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Procure o arquivo teste.")])]
        )

        called_tools_c = []
        turn = session.receive()
        async for resp in turn:
            if resp.tool_call:
                called_tools_c = [fc.name for fc in resp.tool_call.function_calls]
                print(f"  • Tool Call recebida: {called_tools_c}")
                fn_resps = await dispatcher.execute_function_calls(resp.tool_call.function_calls)
                await session.send_tool_response(function_responses=fn_resps)
            if resp.server_content and resp.server_content.turn_complete:
                break

        passed_c = len(called_tools_c) > 0 and ("search_files" in called_tools_c or "list_files" in called_tools_c)
        results["Teste C (Ferramenta: pesquisa de arquivos)"] = "PASS" if passed_c else "FAIL"
        print(f"  [RESULTADO TESTE C] {'PASS' if passed_c else 'FAIL'}")

    # -------------------------------------------------------------
    # TESTE D: Conversa Contínua Multi-turn (3 turnos com contexto)
    # -------------------------------------------------------------
    print("\n>>> EXECUTANDO TESTE D: Conversa Contínua Multi-turn (3 Turnos)...")
    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        # Turno 1: "Olá."
        print("  • Turno 1: 'Olá.'")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Olá.")])]
        )
        async for resp in session.receive():
            if resp.server_content and resp.server_content.turn_complete:
                break

        # Turno 2: "Qual é a capital da França?"
        print("  • Turno 2: 'Qual é a capital da França?'")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Qual é a capital da França?")])]
        )
        t2_text = ""
        async for resp in session.receive():
            if resp.server_content:
                if resp.server_content.output_transcription:
                    t2_text += resp.server_content.output_transcription.text or ""
                if resp.server_content.turn_complete:
                    break
        print(f"    Resposta Turno 2: '{t2_text.strip()}'")

        # Turno 3: "E quantos habitantes ela tem aproximadamente?"
        print("  • Turno 3: 'E quantos habitantes ela tem aproximadamente?' (dependente de 'ela' = Paris)")
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="E quantos habitantes ela tem aproximadamente?")])]
        )
        t3_text = ""
        async for resp in session.receive():
            if resp.server_content:
                if resp.server_content.output_transcription:
                    t3_text += resp.server_content.output_transcription.text or ""
                if resp.server_content.turn_complete:
                    break
        print(f"    Resposta Turno 3: '{t3_text.strip()}'")

        # Contexto validado: Turno 2 deve mencionar Paris, Turno 3 deve responder sobre a população de Paris
        passed_d = ("paris" in t2_text.lower() or "paris" in t3_text.lower()) and len(t3_text.strip()) > 5
        results["Teste D (Conversação multi-turn com contexto)"] = "PASS" if passed_d else "FAIL"
        print(f"  [RESULTADO TESTE D] {'PASS' if passed_d else 'FAIL'}")

    # -------------------------------------------------------------
    # TESTE E: Interrupção / Barge-in
    # -------------------------------------------------------------
    print("\n>>> EXECUTANDO TESTE E: Barge-in / Interrupção...")
    from backend.core.live_engine import LiveAudioEngine
    test_engine = LiveAudioEngine()
    test_engine.audio_in_queue = asyncio.Queue()
    # Simular 20 chunks na fila de reprodução (som ativo)
    for _ in range(20):
        test_engine.audio_in_queue.put_nowait(b"\x11" * 1024)
    qsize_before = test_engine.audio_in_queue.qsize()

    # Disparar barge-in
    t_barge_0 = time.time()
    test_engine.clear_audio_queue()
    t_barge_duration = time.time() - t_barge_0
    qsize_after = test_engine.audio_in_queue.qsize()

    passed_e = (qsize_before == 20) and (qsize_after == 0) and (t_barge_duration < 0.010)
    latencies["barge_in_clear_time"] = t_barge_duration
    results["Teste E (Barge-in / Interrupção imediata)"] = "PASS" if passed_e else "FAIL"
    print(f"  [RESULTADO TESTE E] {'PASS' if passed_e else 'FAIL'}")
    print(f"  • Chunks descartados: {qsize_before} -> {qsize_after} em {t_barge_duration*1000:.3f}ms")

    # -------------------------------------------------------------
    # RELATÓRIO FINAL
    # -------------------------------------------------------------
    print("\n" + "=" * 70)
    print("                        RESUMO DOS TESTES")
    print("=" * 70)
    for test_name, status in results.items():
        print(f"  {test_name:<45}: {status}")

    print("\n" + "=" * 70)
    print("                     LATÊNCIAS MEDIDAS")
    print("=" * 70)
    for k, v in latencies.items():
        print(f"  {k:<35}: {v*1000:.1f} ms ({v:.3f} s)")


if __name__ == "__main__":
    asyncio.run(run_test_suite())
