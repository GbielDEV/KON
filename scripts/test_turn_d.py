import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.core.live_engine import KON_SYSTEM_INSTRUCTION, MODEL_NAME

load_dotenv()


async def test_multi_turn():
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        input_audio_transcription={},
        system_instruction=KON_SYSTEM_INSTRUCTION,
    )

    print("\n--- TESTANDO MULTI-TURN NO GEMINI LIVE ---", flush=True)

    async with client.aio.live.connect(model=MODEL_NAME, config=config) as session:
        # Turno 1: "Olá"
        print("\n[Turno 1] Enviando 'Olá'...", flush=True)
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Olá.")])]
        )
        async for resp in session.receive():
            if resp.server_content and resp.server_content.output_transcription:
                print(resp.server_content.output_transcription.text, end="", flush=True)
            if resp.server_content and resp.server_content.turn_complete:
                print(" [Fim Turno 1]", flush=True)
                break

        # Turno 2: "Qual é a capital da França?"
        print("\n[Turno 2] Enviando 'Qual é a capital da França?'...", flush=True)
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="Qual é a capital da França?")])]
        )
        t2_text = ""
        async for resp in session.receive():
            if resp.server_content and resp.server_content.output_transcription:
                t2_text += resp.server_content.output_transcription.text or ""
                print(resp.server_content.output_transcription.text, end="", flush=True)
            if resp.server_content and resp.server_content.turn_complete:
                print(" [Fim Turno 2]", flush=True)
                break

        # Turno 3: "E quantos habitantes ela tem aproximadamente?"
        print("\n[Turno 3] Enviando 'E quantos habitantes ela tem aproximadamente?'...", flush=True)
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text="E quantos habitantes ela tem aproximadamente?")])]
        )
        t3_text = ""
        async for resp in session.receive():
            if resp.server_content and resp.server_content.output_transcription:
                t3_text += resp.server_content.output_transcription.text or ""
                print(resp.server_content.output_transcription.text, end="", flush=True)
            if resp.server_content and resp.server_content.turn_complete:
                print(" [Fim Turno 3]", flush=True)
                break

    print(f"\nTurno 2 capturou: {t2_text.strip()}", flush=True)
    print(f"Turno 3 capturou: {t3_text.strip()}", flush=True)
    assert "paris" in t2_text.lower() or "paris" in t3_text.lower()
    print("\n>>> SUCESSO: Contexto preservado nos 3 turnos!", flush=True)


if __name__ == "__main__":
    asyncio.run(test_multi_turn())
