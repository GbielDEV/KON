"""
Main entry point for the KON Assistant backend.
Supports direct server execution and automated self-test mode (--test-mode).
"""
import sys
import argparse
import uvicorn
from backend.core.config import get_settings
from backend.core.kon import KONCore
from backend.core.state import AssistantState
from backend.core.events import EventBus, Event, EventType
from backend.core.logger import kon_logger
from backend.computer.windows import WindowsService
from backend.computer.system import SystemTelemetry
from backend.server.ws_server import create_app


def run_self_test() -> bool:
    """
    Executes a comprehensive internal sanity check of KON V1 components.
    """
    print("\n" + "="*50)
    print(" INICIANDO AUTO-TESTE DO BACKEND KON (TEST-MODE)")
    print("="*50)

    success = True

    # 1. State Machine Test
    try:
        core = KONCore()
        assert core.state in (AssistantState.BOOT, AssistantState.IDLE), f"Expected BOOT or IDLE, got {core.state}"
        core.set_state(AssistantState.LISTENING)
        assert core.state == AssistantState.LISTENING
        core.set_state(AssistantState.IDLE)
        assert core.state == AssistantState.IDLE
        print("  [OK] Maquina de estados: BOOT -> LISTENING -> IDLE")
    except Exception as exc:
        print(f"  [FAIL] Teste de Estado: {exc}")
        success = False

    # 2. EventBus Test
    try:
        bus = EventBus()
        received = []
        bus.subscribe(EventType.STATE_CHANGED.value, lambda ev: received.append(ev))
        bus.publish(Event.state_changed("THINKING"))
        assert len(received) == 1, "Event not received"
        assert received[0].data.get("state") == "THINKING"
        print("  [OK] EventBus: inscricao, publicacao e entrega de eventos")
    except Exception as exc:
        print(f"  [FAIL] Teste de EventBus: {exc}")
        success = False

    # 3. Windows Directory Detection
    try:
        user = WindowsService.get_current_user()
        home = WindowsService.get_user_home()
        downloads = WindowsService.get_downloads_dir()
        desktop = WindowsService.get_desktop_dir()
        assert user, "Username is empty"
        assert home.exists(), f"User home {home} does not exist"
        print(f"  [OK] Windows Service: Usuario='{user}', Home='{home}', Downloads='{downloads}', Desktop='{desktop}'")
    except Exception as exc:
        print(f"  [FAIL] Teste Windows Service: {exc}")
        success = False

    # 4. System Telemetry Test
    try:
        cpu = SystemTelemetry.get_cpu_percent()
        ram = SystemTelemetry.get_ram_info()
        uptime = SystemTelemetry.get_uptime_seconds()
        assert isinstance(cpu, float)
        assert "percent" in ram and ram["percent"] > 0
        print(f"  [OK] Telemetria real: CPU={cpu}%, RAM={ram['percent']}% ({ram['used_gb']}GB / {ram['total_gb']}GB), Uptime={uptime}s")
    except Exception as exc:
        print(f"  [FAIL] Teste Telemetria: {exc}")
        success = False

    # 5. SQLite Persistence Test
    try:
        core.memory.log_command("test-command", "IDLE", "SUCCESS", "Autoteste executado")
        hist = core.memory.get_recent_history(1)
        assert len(hist) > 0
        print("  [OK] Banco de Dados SQLite: data/kon.db gravando comandos com sucesso")
    except Exception as exc:
        print(f"  [FAIL] Teste Banco SQLite: {exc}")
        success = False

    # 6. FastAPI App & Routes Test
    try:
        from fastapi.testclient import TestClient
        app = create_app(core)
        client = TestClient(app)

        # /api/health
        res_health = client.get("/api/health")
        assert res_health.status_code == 200, f"Health check failed: {res_health.status_code}"
        assert res_health.json()["status"] == "ok"

        # /api/state
        res_state = client.get("/api/state")
        assert res_state.status_code == 200
        assert res_state.json()["state"] == "IDLE"

        # /api/telemetry
        res_telem = client.get("/api/telemetry")
        assert res_telem.status_code == 200
        assert "cpu_percent" in res_telem.json()
        assert "microphone_available" in res_telem.json()

        print("  [OK] FastAPI Endpoints: /api/health, /api/state e /api/telemetry (com métricas de voz) validados")
    except Exception as exc:
        print(f"  [FAIL] Teste Endpoints FastAPI: {exc}")
        success = False

    # 7. Gemini Live Tool Dispatcher & Application Resolution
    try:
        from backend.ai.gemini_tools import convert_tool_spec_to_declaration
        from backend.computer.applications import ApplicationManager
        spec = core.tool_registry.get_tool("open_application")
        assert spec is not None, "open_application spec not found"
        decl = convert_tool_spec_to_declaration(spec)
        assert decl["name"] == "open_application"
        assert "parameters" in decl

        chrome_path = ApplicationManager.resolve_application_path("chrome")
        assert chrome_path is not None and chrome_path.exists()

        voice_telem = core.get_voice_telemetry()
        assert "model" in voice_telem
        assert voice_telem["native_audio"] is True
        print(f"  [OK] Gemini Live Tools & Windows: Tool='{decl['name']}', Chrome='{chrome_path}', Modelo='{voice_telem['model']}'")
    except Exception as exc:
        print(f"  [FAIL] Teste Gemini Live Tools: {exc}")
        success = False

    print("="*50)
    if success:
        print(" TODOS OS TESTES DO BACKEND PASSARAM COM SUCESSO!")
        print("="*50 + "\n")
        return True
    else:
        print(" FALHA EM UM OU MAIS TESTES DO BACKEND.")
        print("="*50 + "\n")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="KON Assistant Core Server")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run comprehensive backend self-tests and exit"
    )
    args = parser.parse_args()

    if args.test_mode:
        ok = run_self_test()
        sys.exit(0 if ok else 1)

    settings = get_settings()
    kon_logger.info(f"Iniciando KON Assistant Server em http://{settings.host}:{settings.port}")

    app = create_app()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info" if settings.debug else "warning"
    )


if __name__ == "__main__":
    main()
