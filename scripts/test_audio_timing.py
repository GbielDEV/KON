"""
Benchmark de latência real com áudio PCM 16kHz controlado.
Mede os tempos exatos desde o início da fala até o retorno da Tool Call e do Áudio.
"""
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

load_dotenv()

CHUNK_SIZE = 1024 * 2  # 2048 bytes = 1024 samples = 64ms


async def test_audio_pipeline():
    pcm_path = Path("test_speech_16k.pcm")
    assert pcm_path.exists(), "test_speech_16k.pcm não encontrado!"
    pcm_bytes = pcm_path.read_bytes()

    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    model = "models/gemini-2.5-flash-native-audio-preview-12-2025"

    registry = get_tool_registry()
    dispatcher = GeminiToolDispatcher(registry)
    tools_config = dispatcher.get_gemini_tools_config()

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        input_audio_transcription={},
        system_instruction=(
            "Você é o assistente KON. Responda imediatamente. "
            "Se o usuário pedir para abrir um aplicativo como o Chrome, execute open_application IMEDIATAMENTE sem hesitar."
        ),
        tools=tools_config
    )

    print("\n" + "=" * 65)
    print(" INICIANDO TESTE CONTROLADO DE LATÊNCIA DE ÁUDIO")
    print("=" * 65)

    async with client.aio.live.connect(model=model, config=config) as session:
        t_start = time.time()
        print(f"[{time.time() - t_start:.3f}s] Sessão conectada.")

        # Event tracking
        events = {}
        stop_event = asyncio.Event()

        async def send_audio_stream():
            # 1. Enviar os 2.48s de áudio simulando tempo real
            offset = 0
            chunk_count = 0
            while offset < len(pcm_bytes) and not stop_event.is_set():
                chunk = pcm_bytes[offset:offset + CHUNK_SIZE]
                offset += CHUNK_SIZE
                chunk_count += 1

                if chunk_count == 1:
                    events["first_audio_sent"] = time.time() - t_start
                    print(f"[{events['first_audio_sent']:.3f}s] Primeiro chunk de áudio enviado.")

                await session.send_realtime_input(audio={"data": chunk, "mime_type": "audio/pcm"})
                await asyncio.sleep(0.064)  # 64ms pace real

            events["speech_stream_finished"] = time.time() - t_start
            print(f"[{events['speech_stream_finished']:.3f}s] Envio da fala do usuário finalizado ({chunk_count} chunks).")

            # 2. Enviar silêncio simulando o microfone após a fala
            silence_chunk = b"\x00" * CHUNK_SIZE
            for _ in range(40):  # ~2.5s de silêncio
                if stop_event.is_set():
                    break
                await session.send_realtime_input(audio={"data": silence_chunk, "mime_type": "audio/pcm"})
                await asyncio.sleep(0.064)

            print(f"[{time.time() - t_start:.3f}s] Fim da transmissão de silêncio.")

        async def receive_stream():
            turn = session.receive()
            first_audio = True

            try:
                async for resp in turn:
                    t_now = time.time() - t_start

                    # Transcrição do usuário
                    if resp.server_content and resp.server_content.input_transcription:
                        t_user = resp.server_content.input_transcription.text
                        if t_user and "first_user_transcription" not in events:
                            events["first_user_transcription"] = t_now
                            print(f"[{t_now:.3f}s] [USER TRANSCRIBED] '{t_user}'")

                    # Model turn parts
                    if resp.server_content and resp.server_content.model_turn:
                        for part in resp.server_content.model_turn.parts:
                            if part.thought and "first_thought" not in events:
                                events["first_thought"] = t_now
                                print(f"[{t_now:.3f}s] [THOUGHT] Modelo gerando raciocínio interno...")
                            if part.text and not part.thought and "first_text" not in events:
                                events["first_text"] = t_now
                                print(f"[{t_now:.3f}s] [TEXT] '{part.text[:50]}'")
                            if part.inline_data and isinstance(part.inline_data.data, bytes) and first_audio:
                                events["first_audio_received"] = t_now
                                first_audio = False
                                print(f"[{t_now:.3f}s] [NATIVE AUDIO] Primeiro áudio recebido do modelo!")

                    # Tool Call
                    if resp.tool_call:
                        fc_names = [fc.name for fc in resp.tool_call.function_calls]
                        events["tool_call_received"] = t_now
                        print(f"[{t_now:.3f}s] [TOOL CALL] Recebida: {fc_names}")

                        t_tool_start = time.time()
                        fn_resps = await dispatcher.execute_function_calls(resp.tool_call.function_calls)
                        events["tool_execution_time"] = time.time() - t_tool_start
                        print(f"[{time.time() - t_start:.3f}s] [TOOL EXECUTED] Duração: {events['tool_execution_time']*1000:.1f}ms")

                        events["tool_response_sent"] = time.time() - t_start
                        print(f"[{events['tool_response_sent']:.3f}s] Enviando tool response de volta ao Gemini...")
                        await session.send_tool_response(function_responses=fn_resps)

                    if resp.server_content and resp.server_content.turn_complete:
                        events["turn_complete"] = t_now
                        print(f"[{t_now:.3f}s] [TURN COMPLETE]")
                        stop_event.set()
                        break

            except Exception as e:
                print(f"Erro em receive: {e}")
            finally:
                stop_event.set()

        await asyncio.wait_for(asyncio.gather(send_audio_stream(), receive_stream()), timeout=25.0)

    print("\n" + "=" * 65)
    print(" RESULTADOS DAS MEDIÇÕES DE LATÊNCIA")
    print("=" * 65)
    for k, v in events.items():
        if "time" in k:
            print(f"  {k}: {v*1000:.1f} ms")
        else:
            print(f"  {k}: {v:.3f} s")

    if "tool_call_received" in events and "speech_stream_finished" in events:
        latency_after_speech = events["tool_call_received"] - events["speech_stream_finished"]
        print(f"\n >>> LATÊNCIA ENTRE O FIM DA FALA E A TOOL CALL: {latency_after_speech:.3f} segundos <<<")

    if "first_audio_received" in events and "tool_response_sent" in events:
        latency_after_tool = events["first_audio_received"] - events["tool_response_sent"]
        print(f" >>> LATÊNCIA ENTRE O RETORNO DA TOOL E O ÁUDIO: {latency_after_tool:.3f} segundos <<<")


if __name__ == "__main__":
    asyncio.run(test_audio_pipeline())
