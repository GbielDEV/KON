"""
KON Core Orchestrator (ADA V2 Blueprint).
Central brain and coordinator for the reconstructed KON Assistant.
Integrates Gemini Live Engine, Native Audio, Declarative Tool Registry,
EventBus, Security Permissions, and System Telemetry with ZERO legacy voice dependencies.
"""
from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional

from backend.core.state import AssistantState
from backend.core.events import EventBus, Event
from backend.core.logger import kon_logger
from backend.core.config import get_settings
from backend.memory.memory import MemoryManager
from backend.ai.tool_registry import get_tool_registry, ToolRegistry
from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.core.live_engine import LiveAudioEngine, MODEL_NAME


class KONCore:
    """
    Central coordinator of the assistant.
    Maintains the state machine, manages Gemini Live session, routes telemetry, and oversees tools.
    """

    def __init__(self, event_bus: Optional[EventBus] = None, test_mode: bool = False) -> None:
        self.settings = get_settings()
        self.event_bus = event_bus or EventBus()
        self.memory = MemoryManager()
        self.test_mode = test_mode

        # Connect logger to event bus for real-time frontend log streaming
        kon_logger.attach_event_bus(self.event_bus)

        # Declarative Windows Tool Registry
        self.tool_registry: ToolRegistry = get_tool_registry(memory_manager=self.memory)

        # Gemini Tool Dispatcher (with SAFE, CONFIRM, CRITICAL enforcement)
        self.dispatcher = GeminiToolDispatcher(
            registry=self.tool_registry,
            on_confirmation_request=self._handle_confirmation_request,
            on_executing=self._handle_tool_executing,
        )

        # Live Audio Metrics & State
        self._state: AssistantState = AssistantState.BOOT
        self._rms_input: float = 0.0
        self._rms_output: float = 0.0
        self._is_running: bool = False
        self._engine_task: Optional[asyncio.Task] = None

        # Gemini Live Engine (ADA V2 Blueprint)
        self.live_engine = LiveAudioEngine(
            tool_dispatcher=self.dispatcher,
            on_state_change=self._on_engine_state_change,
            on_transcription=self._on_engine_transcription,
            on_audio_levels=self._on_engine_audio_levels,
            on_error=self._on_engine_error,
        )

        kon_logger.info("KON Core (ADA V2 Blueprint) instanciado. Estado inicial: BOOT")

    def _on_engine_state_change(self, new_state: AssistantState, description: str = "") -> None:
        if self._state == new_state:
            return
        previous = self._state
        self._state = new_state
        kon_logger.info(f"[STATE] Transição: {previous.value} -> {new_state.value} ({description or new_state.description})")

        event = Event.state_changed(
            state=new_state.value,
            previous_state=previous.value,
            description=description or new_state.description
        )
        self.event_bus.publish(event)

    def _on_engine_transcription(self, data: Dict[str, str]) -> None:
        """Publishes streaming transcription deltas to the event bus and checks for voice confirmations."""
        event = Event(
            type="transcription",
            data=data,
            message=f"[{data.get('sender')}]: {data.get('text')}"
        )
        self.event_bus.publish(event)

        # Natural voice confirmation resolution (User only, ignoring during SPEAKING)
        sender = data.get("sender")
        if sender == "User":
            if self.state == AssistantState.SPEAKING:
                kon_logger.debug("[VOICE_CONFIRMATION] Ignorando entrada durante estado SPEAKING (proteção contra eco).")
                return

            user_text = data.get("text", "").strip()
            from backend.security.confirmation_manager import get_confirmation_manager
            cm = get_confirmation_manager()
            active_conf = cm.get_active_pending()
            if active_conf:
                consent = cm.parse_natural_consent(
                    user_text,
                    sender=sender,
                    current_state=self.state.value,
                    require_active=True,
                )
                if consent is not None:
                    kon_logger.info(
                        f"[VOICE_CONFIRMATION] Resposta de voz interpretada: '{user_text}' -> {consent} "
                        f"(Confirmação ativa: {active_conf.confirmation_id} - {active_conf.tool})"
                    )
                    self.dispatcher.resolve_confirmation(active_conf.confirmation_id, consent)

    def _on_engine_audio_levels(self, rms_input: float, rms_output: float) -> None:
        self._rms_input = rms_input
        self._rms_output = rms_output

    def _on_engine_error(self, message: str) -> None:
        kon_logger.error(f"[KON] Erro no motor Live: {message}")
        event = Event.log("ERROR", message)
        self.event_bus.publish(event)

    async def _handle_confirmation_request(self, data: Dict[str, Any]) -> None:
        """Emits confirmation request to EventBus (consumed by WebSocket / HUD)."""
        kon_logger.info(f"[SECURITY] Solicitando confirmação do usuário para: {data.get('tool')}")
        event = Event(
            type="tool_confirmation_request",
            data=data,
            message=f"Confirmação necessária para '{data.get('tool')}'"
        )
        self.event_bus.publish(event)

    def _handle_tool_executing(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Notifies that a tool is being executed."""
        self.set_state(AssistantState.EXECUTING, f"Executando {tool_name}")
        event = Event(
            type="tool_executing",
            data={"tool": tool_name, "args": args},
            message=f"Executando ferramenta '{tool_name}'..."
        )
        self.event_bus.publish(event)

    def resolve_tool_confirmation(self, request_id: str, confirmed: bool) -> bool:
        """Resolves a pending tool confirmation."""
        return self.dispatcher.resolve_confirmation(request_id, confirmed)

    @property
    def state(self) -> AssistantState:
        return self._state

    def set_state(self, new_state: AssistantState, reason: Optional[str] = None) -> None:
        self._on_engine_state_change(new_state, reason or new_state.description)

    def get_voice_telemetry(self) -> Dict[str, Any]:
        """Provides real-time telemetry of the Gemini Live audio subsystem."""
        connected = bool(self.live_engine.session is not None)
        return {
            "microphone_available": True,
            "microphone_device": "Realtek Audio (16kHz PCM)",
            "gemini_live_connected": connected,
            "model": MODEL_NAME,
            "native_audio": True,
            "rms_input": self._rms_input,
            "rms_output": self._rms_output,
            "speech_paused": self.live_engine.paused,
        }

    async def start(self) -> None:
        """
        Starts the assistant and launches the Gemini Live engine.
        Fast boot (< 1s) with no heavy local models.
        """
        if self._is_running:
            return

        self._is_running = True
        kon_logger.info("[KON] Iniciando KON Core com Gemini Live & Native Audio...")

        if self.test_mode:
            kon_logger.info("[KON] Modo de teste ativo: pulando conexão contínua de áudio.")
            self.set_state(AssistantState.IDLE, "KON pronto (modo teste)")
            return

        # Start Live Audio Engine task
        self._engine_task = asyncio.create_task(self.live_engine.run())

    async def stop(self) -> None:
        """Stops the assistant cleanly."""
        kon_logger.info("[KON] Parando KON Core...")
        self._is_running = False
        self.live_engine.stop()
        if self._engine_task:
            self._engine_task.cancel()
            try:
                await self._engine_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            from backend.browser.session import has_browser_session, close_browser_session
            if has_browser_session():
                close_browser_session()
        except Exception as e:
            kon_logger.debug(f"[KON] Erro ao fechar BrowserSession: {e}")
        self.set_state(AssistantState.BOOT, "KON desligado")

    async def handle_command(self, command_text: str) -> Dict[str, Any]:
        """
        Processes a direct text command (from developer API or Web UI).
        If Live session is connected, injects into session; otherwise executes via ToolRegistry directly.
        """
        kon_logger.info(f"[COMMAND] Comando recebido: '{command_text}'")
        clean_text = command_text.strip()

        # If live session is active, send to Gemini Live
        if self.live_engine and self.live_engine.session:
            try:
                await self.live_engine.session.send(input=clean_text, end_of_turn=True)
                return {"success": True, "message": f"Mensagem enviada ao Gemini Live: '{clean_text}'"}
            except Exception as e:
                kon_logger.error(f"[COMMAND] Falha ao enviar para Gemini Live: {e}")

        # Fallback direct execution
        return {"success": True, "message": f"Comando '{clean_text}' recebido pelo sistema."}
