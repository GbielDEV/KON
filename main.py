"""
Root entry point for the KON Personal Assistant.
Running `python main.py` automatically initializes the microphone, enters IDLE,
and starts continuous conversational interaction with Gemini Live Native Audio.
No activation word or UI clicks are required.
"""
import sys
import argparse
import asyncio
import uvicorn

from backend.core.config import get_settings
from backend.core.kon import KONCore
from backend.core.logger import kon_logger
from backend.server.ws_server import create_app


async def run_kon():
    """
    Initializes KONCore, starts FastAPI and WebSocket server,
    and runs the continuous voice listener.
    """
    settings = get_settings()
    kon_logger.info("=" * 60)
    kon_logger.info("   INICIANDO ASSISTENTE KON (ADA V2 / GEMINI LIVE ENGINE)")
    kon_logger.info("=" * 60)
    kon_logger.info("[AUDIO] Inicializando Gemini Live Native Audio (16kHz in / 24kHz out)...")

    # Instantiate KON Core
    core = KONCore()

    # Create FastAPI app with core attached
    app = create_app(core)

    # Ensure port is free to prevent WinError 10048 socket conflicts
    try:
        import socket
        import subprocess
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", settings.port)) == 0:
                kon_logger.warning(f"[SERVER] Porta {settings.port} ocupada. Liberando...")
                subprocess.run(
                    f'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort {settings.port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"',
                    shell=True,
                    capture_output=True,
                )
    except Exception:
        pass

    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level="info" if settings.debug else "warning",
    )
    server = uvicorn.Server(config)

    kon_logger.info(f"Servidor FastAPI & WebSocket ativo em http://{settings.host}:{settings.port}")
    kon_logger.info("Gemini Live ativo. Pode falar.")
    kon_logger.info("Pressione Ctrl+C para encerrar.")

    await server.serve()


def main():
    parser = argparse.ArgumentParser(description="KON Assistant Voice Core")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Executes internal sanity check and exits",
    )
    args = parser.parse_args()

    if args.test_mode:
        from backend.main import run_self_test
        ok = run_self_test()
        sys.exit(0 if ok else 1)

    try:
        asyncio.run(run_kon())
    except (KeyboardInterrupt, SystemExit):
        kon_logger.info("KON encerrado pelo usuário.")


if __name__ == "__main__":
    main()
