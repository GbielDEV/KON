"""
Diagnóstico detalhado de latência e instrumentação do pipeline de voz.
Mede os tempos exatos em cada etapa:
1. Início da fala (RMS > threshold)
2. Envio de áudio para a Live API
3. Detecção de fala pelo Gemini (input_transcription)
4. Fim da fala (silêncio)
5. Primeira resposta do Gemini (thought/texto)
6. Recepção de Tool Call
7. Execução da Ferramenta
8. Envio de Tool Response
9. Primeiro chunk de áudio (Native Audio)
10. Início da reprodução no speaker
"""
import os
import time
import math
import struct
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.ai.tool_registry import get_tool_registry

load_dotenv()

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024


async def run_diagnostics(prompt_audio_seconds=4.0):
    p = pyaudio.PyAudio()
    mic_info = p.get_default_input_device_info()
    speaker_info = p.get_default_output_device_info()

    print(f"[DIAG] Microfone: {mic_info['name']} (Index {mic_info['index']})")
    print(f"[DIAG] Alto-falante: {speaker_info['name']} (Index {speaker_info['index']})")

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
            "Você é o KON, assistente para Windows. Seja extremamente direto e conciso. "
            "Quando o usuário pedir para abrir um aplicativo ou checar sistema, acione a ferramenta IMEDIATAMENTE."
        ),
        tools=tools_config
    )

    print("[DIAG] Conectando à Gemini Live API...")
    t_conn_start = time.time()
    async with client.aio.live.connect(model=model, config=config) as session:
        t_conn_done = time.time()
        print(f"[DIAG] Conectado em {t_conn_done - t_conn_start:.3f}s")

        # Abre stream do microfone
        in_stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SEND_SAMPLE_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_SIZE
        )

        # Abre stream de saída (alto-falante)
        out_stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
            output_device_index=speaker_info["index"]
        )

        timestamps = {}
        stop_event = asyncio.Event()

        print("\n" + "="*60)
        print(" [DIAG] FALE AGORA NO MICROFONE (Ex: 'KON, abra a calculadora')")
        print(f" [DIAG] Gravando e transmitindo por {prompt_audio_seconds}s...")
        print("="*60 + "\n")

        t_capture_start = time.time()
        timestamps["capture_start"] = t_capture_start
        speech_detected = False

        async def send_mic():
            nonlocal speech_detected
            chunks_sent = 0
            while not stop_event.is_set():
                elapsed = time.time() - t_capture_start
                if elapsed > prompt_audio_seconds:
                    # Concluiu envio da fala
                    if "speech_ended" not in timestamps:
                        timestamps["speech_ended"] = time.time()
                        print(f"[DIAG] [{timestamps['speech_ended'] - t_capture_start:.3f}s] Fim da janela de fala do usuário.")
                    await asyncio.sleep(0.05)
                    continue

                data = await asyncio.to_thread(in_stream.read, CHUNK_SIZE, exception_on_overflow=False)
                
                # RMS
                count = len(data) // 2
                shorts = struct.unpack(f"<{count}h", data)
                sum_sq = sum(s ** 2 for s in shorts)
                rms = int(math.sqrt(sum_sq / count)) if count > 0 else 0

                if rms > 600 and not speech_detected:
                    speech_detected = True
                    timestamps["speech_detected_local"] = time.time()
                    print(f"[DIAG] [{timestamps['speech_detected_local'] - t_capture_start:.3f}s] Fala detectada localmente (RMS: {rms})")

                t_send = time.time()
                # Use send_realtime_input for low-latency streaming
                try:
                    await session.send_realtime_input(audio={"data": data, "mime_type": "audio/pcm"})
                except Exception:
                    await session.send(input={"data": data, "mime_type": "audio/pcm"}, end_of_turn=False)
                
                chunks_sent += 1
                if chunks_sent == 1:
                    timestamps["first_chunk_sent"] = time.time()
                    print(f"[DIAG] [{timestamps['first_chunk_sent'] - t_capture_start:.3f}s] Primeiro chunk de áudio enviado ao Gemini")

        async def receive_gemini():
            turn = session.receive()
            first_response = True
            first_audio = True

            try:
                async for response in turn:
                    t_now = time.time() - t_capture_start

                    # 1. Transcrição do usuário (Gemini detectou fala)
                    if response.server_content and response.server_content.input_transcription:
                        txt = response.server_content.input_transcription.text
                        if txt and "gemini_recognized_user" not in timestamps:
                            timestamps["gemini_recognized_user"] = time.time()
                            print(f"[DIAG] [{t_now:.3f}s] [GEMINI LISTENING] Usuário transcrito: '{txt}'")

                    # 2. Resposta não-áudio (Thought / Text)
                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.thought:
                                if "first_thought" not in timestamps:
                                    timestamps["first_thought"] = time.time()
                                    print(f"[DIAG] [{t_now:.3f}s] [GEMINI THOUGHT] Modelo gerando raciocínio interno...")
                            if part.text and not part.thought:
                                if "first_text" not in timestamps:
                                    timestamps["first_text"] = time.time()
                                    print(f"[DIAG] [{t_now:.3f}s] [GEMINI TEXT] Modelo gerou texto: '{part.text[:60]}'")
                            if part.inline_data and isinstance(part.inline_data.data, bytes):
                                if first_audio:
                                    timestamps["first_audio_received"] = time.time()
                                    first_audio = False
                                    print(f"[DIAG] [{t_now:.3f}s] [NATIVE AUDIO] Primeiro chunk de áudio recebido ({len(part.inline_data.data)} bytes)!")
                                
                                # Reproduz no alto-falante
                                t_play_start = time.time()
                                if "speaker_started" not in timestamps:
                                    timestamps["speaker_started"] = t_play_start
                                    print(f"[DIAG] [{t_play_start - t_capture_start:.3f}s] [SPEAKER] Áudio começando a tocar no alto-falante!")
                                await asyncio.to_thread(out_stream.write, part.inline_data.data)

                    # 3. Tool Call
                    if response.tool_call:
                        fc_list = [fc.name for fc in response.tool_call.function_calls]
                        timestamps["tool_call_received"] = time.time()
                        print(f"[DIAG] [{t_now:.3f}s] [TOOL CALL] Gemini solicitou ferramentas: {fc_list}")

                        t_exec_start = time.time()
                        fn_resps = await dispatcher.execute_function_calls(response.tool_call.function_calls)
                        t_exec_done = time.time()
                        timestamps["tool_exec_duration"] = t_exec_done - t_exec_start
                        print(f"[DIAG] [{t_exec_done - t_capture_start:.3f}s] [TOOL EXECUTED] Duração: {timestamps['tool_exec_duration']*1000:.1f}ms")

                        # Envia resposta da ferramenta de volta
                        timestamps["tool_response_sent"] = time.time()
                        print(f"[DIAG] [{timestamps['tool_response_sent'] - t_capture_start:.3f}s] Enviando tool_response de volta ao Gemini...")
                        await session.send_tool_response(function_responses=fn_resps)

                    if response.server_content and response.server_content.turn_complete:
                        timestamps["turn_complete"] = time.time()
                        print(f"[DIAG] [{timestamps['turn_complete'] - t_capture_start:.3f}s] [TURN COMPLETE] Turno concluído!")
                        break

            except Exception as e:
                print(f"[DIAG] Erro em receive_gemini: {e}")
            finally:
                stop_event.set()

        try:
            await asyncio.wait_for(
                asyncio.gather(send_mic(), receive_gemini()),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            print("[DIAG] Timeout de 20s atingido no teste.")
            stop_event.set()

        in_stream.stop_stream()
        in_stream.close()
        out_stream.stop_stream()
        out_stream.close()

    p.terminate()

    # Resumo
    print("\n" + "="*60)
    print(" TABELA DE LATÊNCIAS MEDIDAS")
    print("="*60)
    t_start = timestamps.get("capture_start", 0)

    for k, v in timestamps.items():
        if k != "capture_start" and k != "tool_exec_duration":
            print(f"  - {k}: +{v - t_start:.3f}s")
        elif k == "tool_exec_duration":
            print(f"  - tool_exec_duration: {v*1000:.1f} ms")


if __name__ == "__main__":
    asyncio.run(run_diagnostics(prompt_audio_seconds=4.0))
