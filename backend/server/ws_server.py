"""
FastAPI application and WebSocket endpoints for KON Assistant (ADA V2 Blueprint).
Provides real-time event broadcasting, streaming transcriptions, audio telemetry,
and tool confirmation flow to the React HUD.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.kon import KONCore
from backend.core.state import AssistantState
from backend.core.events import Event, EventType
from backend.core.logger import kon_logger
from backend.core.config import get_settings
from backend.computer.system import SystemTelemetry
from backend.server.connection_manager import ConnectionManager


class StateChangeRequest(BaseModel):
    state: str
    reason: Optional[str] = "Manual API trigger"


class ToolConfirmRequest(BaseModel):
    id: str
    confirmed: bool


def create_app(kon_core: Optional[KONCore] = None) -> FastAPI:
    """
    Application factory for KON FastAPI service.
    """
    _ = get_settings()
    core = kon_core or KONCore()
    manager = ConnectionManager()
    telemetry_task: Optional[asyncio.Task] = None
    main_loop = None

    def on_event_dispatched(event: Event) -> None:
        """Publishes all internal EventBus events to connected WebSocket HUD clients."""
        if main_loop and main_loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(manager.broadcast(event.model_dump()), main_loop)
            except Exception:
                pass
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager.broadcast(event.model_dump()))
            except RuntimeError:
                pass

    core.event_bus.subscribe_all(on_event_dispatched)

    async def telemetry_broadcast_loop() -> None:
        """
        Background task to push real system telemetry and audio metrics
        every 1.5 seconds to connected clients.
        """
        while True:
            try:
                await asyncio.sleep(1.5)
                if manager.active_connections:
                    snapshot = SystemTelemetry.snapshot(core.state.value, core.get_voice_telemetry())
                    event = Event.telemetry(snapshot)
                    await manager.broadcast(event.model_dump())
            except asyncio.CancelledError:
                break
            except Exception as err:
                kon_logger.debug(f"[SERVER] Erro no loop de telemetria: {err}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal main_loop
        main_loop = asyncio.get_running_loop()
        kon_logger.info("[SERVER] Iniciando servidor KON FastAPI / WebSocket...")

        # Start KON Core & Gemini Live Engine
        asyncio.create_task(core.start())

        nonlocal telemetry_task
        telemetry_task = asyncio.create_task(telemetry_broadcast_loop())
        yield

        # Shutdown
        kon_logger.info("[SERVER] Finalizando servidor KON...")
        if telemetry_task:
            telemetry_task.cancel()
        await core.stop()

    app = FastAPI(
        title="KON Assistant API (ADA V2 Blueprint)",
        version="2.0.0",
        description="REST & WebSocket API for KON Personal Assistant powered by Gemini Live",
        lifespan=lifespan
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.core = core
    app.state.manager = manager

    @app.get("/api/health")
    async def get_health() -> Dict[str, Any]:
        """Health check endpoint."""
        voice_telem = core.get_voice_telemetry()
        return {
            "status": "ok",
            "service": "KON Core",
            "architecture": "ADA V2 Blueprint (Gemini Live Native Audio)",
            "version": "2.0.0",
            "state": core.state.value,
            "description": core.state.description,
            "gemini_live_connected": voice_telem.get("gemini_live_connected", False),
            "model": voice_telem.get("model", "unknown"),
        }

    @app.get("/api/state")
    async def get_state() -> Dict[str, Any]:
        """Returns current state and uptime."""
        telemetry = SystemTelemetry.snapshot(core.state.value)
        return {
            "state": core.state.value,
            "description": core.state.description,
            "uptime_seconds": telemetry["uptime_seconds"],
            "uptime_formatted": telemetry["uptime_formatted"]
        }

    @app.post("/api/state")
    async def set_state(payload: StateChangeRequest) -> Dict[str, Any]:
        """Allows manually updating state during testing."""
        try:
            target_state = AssistantState.from_string(payload.state)
            core.set_state(target_state, reason=payload.reason)
            return {
                "success": True,
                "state": core.state.value,
                "description": core.state.description
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/telemetry")
    async def get_telemetry() -> Dict[str, Any]:
        """Returns hardware and Gemini Live audio metrics."""
        return SystemTelemetry.snapshot(core.state.value, core.get_voice_telemetry())

    @app.post("/api/confirm-tool")
    async def confirm_tool(payload: ToolConfirmRequest) -> Dict[str, Any]:
        """Endpoint to confirm or deny tool execution."""
        resolved = core.resolve_tool_confirmation(payload.id, payload.confirmed)
        return {"success": resolved, "id": payload.id, "confirmed": payload.confirmed}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        Primary bidirectional WebSocket channel between React HUD and Python backend.
        """
        await manager.connect(websocket)

        # Send initial state, welcome message, and telemetry snapshot upon connection
        initial_telemetry = SystemTelemetry.snapshot(core.state.value, core.get_voice_telemetry())
        await manager.send_personal({
            "type": EventType.STATE_CHANGED.value,
            "data": {
                "state": core.state.value,
                "description": core.state.description
            },
            "timestamp": initial_telemetry["timestamp"]
        }, websocket)

        await manager.send_personal({
            "type": EventType.LOG.value,
            "level": "INFO",
            "message": "Sistemas online. Arquitetura Gemini Live / ADA V2 ativa.",
            "timestamp": initial_telemetry["timestamp"],
            "data": {"service": "KON Core"}
        }, websocket)

        await manager.send_personal({
            "type": EventType.TELEMETRY.value,
            "data": initial_telemetry,
            "timestamp": initial_telemetry["timestamp"]
        }, websocket)

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "command":
                    command_text = data.get("command", "")
                    response = await core.handle_command(command_text)
                    await manager.send_personal({
                        "type": EventType.SYSTEM_RESPONSE.value,
                        "data": response,
                        "message": response.get("message", "Comando recebido.")
                    }, websocket)

                elif msg_type == "confirm_tool":
                    req_id = data.get("id")
                    confirmed = data.get("confirmed", False)
                    core.resolve_tool_confirmation(req_id, confirmed)
                    await manager.send_personal({
                        "type": EventType.LOG.value,
                        "level": "INFO",
                        "message": f"Confirmação resolvida: {'Autorizado' if confirmed else 'Negado'}"
                    }, websocket)

                elif msg_type == "pause_audio":
                    core.live_engine.set_paused(True)

                elif msg_type == "resume_audio":
                    core.live_engine.set_paused(False)

                elif msg_type == "ping":
                    await manager.send_personal({"type": "pong"}, websocket)

                elif msg_type == "set_state":
                    requested_state = data.get("state", "")
                    try:
                        new_st = AssistantState.from_string(requested_state)
                        core.set_state(new_st)
                    except Exception as exc:
                        await manager.send_personal({
                            "type": EventType.ERROR.value,
                            "message": str(exc)
                        }, websocket)

        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as err:
            kon_logger.debug(f"[SERVER] Conexão WebSocket encerrada: {err}")
            manager.disconnect(websocket)

    return app
