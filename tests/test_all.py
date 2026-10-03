"""
Unit and Integration tests for KON Assistant Core.
"""
import pytest
from fastapi.testclient import TestClient
from backend.core.state import AssistantState
from backend.core.events import EventBus, Event, EventType
from backend.core.config import get_settings
from backend.core.kon import KONCore
from backend.computer.windows import WindowsService
from backend.computer.system import SystemTelemetry
from backend.server.ws_server import create_app


def test_assistant_state():
    assert AssistantState.IDLE.value == "IDLE"
    assert AssistantState.IDLE.description == "KON está aguardando"
    assert AssistantState.from_string("listening") == AssistantState.LISTENING
    assert AssistantState.from_string("ERROR") == AssistantState.ERROR

    with pytest.raises(ValueError):
        AssistantState.from_string("INVALID_STATE")


def test_event_bus():
    bus = EventBus()
    events = []

    def handler(ev):
        events.append(ev)

    bus.subscribe(EventType.STATE_CHANGED.value, handler)
    bus.publish(Event.state_changed("LISTENING"))

    assert len(events) == 1
    assert events[0].type == "state_changed"
    assert events[0].data["state"] == "LISTENING"


def test_kon_core_state_transition():
    core = KONCore()
    # KONCore starts in BOOT state until start() is called and models finish loading
    assert core.state == AssistantState.BOOT

    core.set_state(AssistantState.THINKING)
    assert core.state == AssistantState.THINKING

    core.set_state(AssistantState.EXECUTING)
    assert core.state == AssistantState.EXECUTING

    core.set_state(AssistantState.IDLE)
    assert core.state == AssistantState.IDLE


def test_configuration():
    settings = get_settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.db_path.name == "kon.db"
    assert settings.log_file.name == "kon.log"


def test_windows_service():
    user = WindowsService.get_current_user()
    home = WindowsService.get_user_home()
    assert user is not None and len(user) > 0
    assert home.exists()


def test_system_telemetry():
    snapshot = SystemTelemetry.snapshot()
    assert "cpu_percent" in snapshot
    assert "ram_percent" in snapshot
    assert "uptime_seconds" in snapshot
    assert "os" in snapshot


def test_api_endpoints():
    core = KONCore()
    app = create_app(core)
    client = TestClient(app)

    # Health — state is BOOT initially (start() not called in unit tests)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["state"] in ("BOOT", "IDLE")

    # State — also BOOT until start() completes
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["state"] in ("BOOT", "IDLE")

    # Change State via API
    r = client.post("/api/state", json={"state": "LISTENING"})
    assert r.status_code == 200
    assert r.json()["state"] == "LISTENING"
    assert core.state == AssistantState.LISTENING


def test_websocket_connection():
    core = KONCore()
    app = create_app(core)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Drain initial handshake messages
        handshake_types = []
        for _ in range(4):
            msg = ws.receive_json()
            handshake_types.append(msg.get("type"))

        assert "state_changed" in handshake_types
        assert "log" in handshake_types
        assert "telemetry" in handshake_types

        # Test sending command
        ws.send_json({"type": "command", "command": "status"})

        # Read until system_response is encountered
        found_response = False
        for _ in range(5):
            resp = ws.receive_json()
            if resp.get("type") == "system_response":
                found_response = True
                assert resp["data"]["success"] is True
                break

        assert found_response, "system_response was not received"
