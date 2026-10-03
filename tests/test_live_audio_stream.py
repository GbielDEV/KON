"""
Test Live Audio Streaming, Native Audio Reception, and Barge-in queue clearing.
"""
import os
import asyncio
import pytest
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.core.live_engine import LiveAudioEngine

load_dotenv()


@pytest.mark.anyio
async def test_live_engine_audio_barge_in_and_streaming():
    engine = LiveAudioEngine()

    # 1. Test Barge-in queue clearing
    engine.audio_in_queue = asyncio.Queue()
    for _ in range(10):
        engine.audio_in_queue.put_nowait(b"\x00" * 1024)
    assert engine.audio_in_queue.qsize() == 10

    # User speaks -> barge-in triggered
    engine.clear_audio_queue()
    assert engine.audio_in_queue.empty(), "A fila de áudio deve estar vazia após o barge-in!"
    print("  [OK] Barge-in: Fila de áudio limpa instantaneamente!")

    # 2. Test Live Session Audio Handshake
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    model = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Você é o KON. Diga apenas 'Sistema operacional online'."
    )

    received_audio_chunks = 0
    received_transcription = ""

    async with client.aio.live.connect(model=model, config=config) as session:
        # Enviar um comando curto de teste
        await session.send(input="KON, teste de áudio.", end_of_turn=True)

        # Aguardar recepção de chunks nativos de áudio
        try:
            async with asyncio.timeout(10.0):
                turn = session.receive()
                async for response in turn:
                    if response.data:
                        received_audio_chunks += 1
                    elif response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if getattr(part, "inline_data", None) and part.inline_data.data:
                                received_audio_chunks += 1
                            elif getattr(part, "text", None):
                                received_transcription += part.text
                    if response.server_content and response.server_content.output_transcription:
                        received_transcription += response.server_content.output_transcription.text or ""
                    if received_audio_chunks >= 3:
                        break
        except asyncio.TimeoutError:
            pass

        assert received_audio_chunks > 0 or len(received_transcription) > 0, "Deveria ter recebido resposta de áudio ou transcrição do Gemini Live!"
    print(f"  [OK] Native Audio: Recebidos {received_audio_chunks} chunks de áudio! Transcrição: '{received_transcription.strip()}'")
