"""
Voice Pipeline Orchestrator and State Machine Integration for KON.
Coordinates:
Activation -> TTS ("Sim?") -> Simple Audio Capture -> STT -> Tool Resolver / Planner -> Tool Registry / Permissions -> Action -> TTS -> IDLE.
"""
from typing import Optional, Callable, Dict, Any
import threading
import time

from backend.core.state import AssistantState
from backend.core.events import EventBus, Event
from backend.core.logger import kon_logger
from backend.memory.memory import MemoryManager

from voice_assistant.audio.capture import AudioCapture
from voice_assistant.audio.simple_capture import SimpleCommandCapture
from voice_assistant.audio.wake_word import WakeWordDetector, OpenWakeWordDetector
from voice_assistant.audio.activation import ActivationManager, WakeWordActivation, DoubleClapActivation
from voice_assistant.stt.speech_recognition_engine import SpeechRecognitionEngine
from voice_assistant.stt.whisper_engine import BaseSTTEngine
from voice_assistant.tts.speak import TextToSpeech

from backend.ai.tool_registry import ToolRegistry, get_tool_registry
from backend.ai.planner import ToolResolver, PlanExecutor, ToolPlan
from backend.ai.loop_guard import LoopGuard


class VoicePipelineOrchestrator:
    """
    Continuous, autonomous voice orchestrator for KON.
    Starts automatically without buttons, listens for activation (Wake Word / Double Clap),
    captures speech with simple energy/RMS threshold, transcribes with faster-whisper,
    resolves multi-step plans with ToolResolver, executes via ToolRegistry and LoopGuard,
    speaks natural responses in Brazilian Portuguese, and returns to IDLE.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        memory_manager: Optional[MemoryManager] = None,
        audio_capture: Optional[AudioCapture] = None,
        wake_word_detector: Optional[WakeWordDetector] = None,
        command_capture: Optional[SimpleCommandCapture] = None,
        stt_engine: Optional[BaseSTTEngine] = None,
        tool_registry: Optional[ToolRegistry] = None,
        tool_resolver: Optional[ToolResolver] = None,
        plan_executor: Optional[PlanExecutor] = None,
        loop_guard: Optional[LoopGuard] = None,
        tts: Optional[TextToSpeech] = None,
        state_callback: Optional[Callable[[AssistantState, Optional[str]], None]] = None,
        # Legacy backward-compatibility parameters:
        vad: Optional[Any] = None,
        use_legacy_vad: bool = False,
        intent_parser: Optional[Any] = None,
        registry: Optional[Any] = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.memory = memory_manager or MemoryManager()
        self.audio_capture = audio_capture or AudioCapture()
        self.wake_detector = wake_word_detector or OpenWakeWordDetector(wake_word="Okay KON", threshold=0.38)
        self.command_capture = command_capture or SimpleCommandCapture()
        self.stt = stt_engine or SpeechRecognitionEngine()
        self.tts = tts or TextToSpeech()
        self.state_callback = state_callback

        # Tool Registry, Planner & LoopGuard
        self.tool_registry = tool_registry or get_tool_registry(memory_manager=self.memory)
        self.loop_guard = loop_guard or LoopGuard(bus=self.event_bus)
        self.tool_resolver = tool_resolver or ToolResolver(registry=self.tool_registry)
        self.plan_executor = plan_executor or PlanExecutor(registry=self.tool_registry, loop_guard=self.loop_guard)

        # Unified Activation Manager (Okay KON primary wake word)
        self.activation_manager = ActivationManager(
            event_bus=self.event_bus,
            wake_word_source=WakeWordActivation(self.wake_detector),
            double_clap_source=DoubleClapActivation(threshold=20000, enabled=False),
        )

        self._state: AssistantState = AssistantState.IDLE
        self._is_running = False
        self._is_cycle_active = False
        self._is_preloaded = False
        self._loop_thread: Optional[threading.Thread] = None

    @property
    def state(self) -> AssistantState:
        return self._state

    def set_state(self, new_state: AssistantState, reason: Optional[str] = None) -> None:
        """
        Updates assistant state, logging with [STATE] and notifying EventBus.
        """
        if self._state == new_state:
            return

        prev = self._state
        self._state = new_state
        state_name = new_state.value
        display_name = "OUVINDO" if new_state == AssistantState.LISTENING else (
            "PROCESSANDO" if new_state == AssistantState.THINKING else state_name
        )
        kon_logger.info(f"[STATE] {display_name}")

        if self.state_callback:
            try:
                self.state_callback(new_state, reason)
            except Exception as exc:
                kon_logger.debug(f"[STATE] Erro no callback de estado: {exc}")

        # Broadcast state change event to EventBus for WebSocket / React monitor
        event = Event.state_changed(
            state=new_state.value,
            previous_state=prev.value,
            description=new_state.description,
        )
        self.event_bus.publish(event)

    def preload_and_warmup(self) -> None:
        """
        Preloads AI and audio models into RAM and warms up execution graphs.
        SentenceTransformer was removed: boot is now lightweight and takes seconds.
        """
        if self._is_preloaded:
            return

        kon_logger.info("[BOOT] Inicializando KON (arquitetura semântica otimizada)...")

        # 1. Wake Word
        kon_logger.info("[BOOT] Carregando Wake Word...")
        if hasattr(self.wake_detector, "preload"):
            self.wake_detector.preload()
        elif hasattr(self.wake_detector, "_initialize_model"):
            self.wake_detector._initialize_model()
        kon_logger.info("[BOOT] Wake Word pronta")

        # 2. STT Engine (SpeechRecognition)
        kon_logger.info("[BOOT] Preparando STT (SpeechRecognitionEngine)...")
        if hasattr(self.stt, "preload"):
            self.stt.preload()
        kon_logger.info("[BOOT] STT pronto (zero modelos neurais pesados em RAM)")

        # 3. Tool Registry
        kon_logger.info(f"[BOOT] Tool Registry pronto ({len(self.tool_registry.list_tools())} ferramentas ativas)")

        # 4. TTS
        kon_logger.info("[BOOT] Inicializando TTS...")
        if hasattr(self.tts, "preload"):
            self.tts.preload()
        kon_logger.info("[BOOT] TTS pronto")

        self._is_preloaded = True
        kon_logger.info("[BOOT] KON pronto para receber comandos de voz gerais")

    def start(self) -> bool:
        """Starts audio capture, wake word detector, and continuous voice loop."""
        if self._is_running:
            return True

        if not self._is_preloaded:
            self.preload_and_warmup()

        self._is_running = True

        # 1. Start wake word detector
        self.wake_detector.start()

        # 2. Start continuous audio stream for activation listening
        if not self.audio_capture.start():
            kon_logger.warning("[MIC] Não foi possível iniciar o microfone.")
            return False

        self.audio_capture.clear_queue()

        # 3. Launch continuous voice loop thread
        self._loop_thread = threading.Thread(
            target=self._continuous_voice_loop,
            name="KON-ContinuousVoiceLoop",
            daemon=True,
        )
        self._loop_thread.start()
        kon_logger.info("[VOICE] Loop contínuo de voz iniciado.")
        self.set_state(AssistantState.IDLE, reason="KON pronto e aguardando ativação")
        return True

    def stop(self) -> None:
        """Stops the continuous voice loop and hardware streams."""
        self._is_running = False
        self.wake_detector.stop()
        self.audio_capture.stop()
        self.set_state(AssistantState.IDLE, reason="Voz desativada")
        kon_logger.info("[VOICE] Loop contínuo de voz finalizado.")

    def _continuous_voice_loop(self) -> None:
        """Consumes chunks during IDLE and triggers voice cycle upon activation."""
        kon_logger.info('[WAKE] Escutando continuamente por ativação (Voz / Duas Palmas)...')
        _prev_was_in_cycle = False

        while self._is_running:
            non_idle = (self._state != AssistantState.IDLE) or self._is_cycle_active

            if non_idle:
                _prev_was_in_cycle = True
                time.sleep(0.05)
                continue

            # Drain residual audio after a cycle
            if _prev_was_in_cycle:
                _prev_was_in_cycle = False
                while not self.audio_capture._queue.empty():
                    try:
                        self.audio_capture._queue.get_nowait()
                    except Exception:
                        break

            # Drop backlog (> 2 chunks = > 160ms old) to keep real-time latency
            if self.audio_capture.get_queue_size() > 2:
                while self.audio_capture.get_queue_size() > 1:
                    try:
                        self.audio_capture._queue.get_nowait()
                    except Exception:
                        break

            chunk, audio_received_at = self.audio_capture.read_chunk_with_timestamp(timeout=0.2)
            if chunk is None or len(chunk) < 2560:
                continue

            t_act_start = time.perf_counter()
            trigger = self.activation_manager.process_audio(chunk)
            t_act_end = time.perf_counter()

            if trigger:
                t_detected = time.time()
                t_det_str = time.strftime("%H:%M:%S") + f".{int((t_detected % 1) * 1000):03d}"
                proc_ms = (t_act_end - t_act_start) * 1000.0

                kon_logger.info(f"[{t_det_str}] [ACTIVATION] Ativação via '{trigger}' confirmada! (inferência: {proc_ms:.2f}ms)")
                self.run_voice_cycle(wake_detected_at=t_detected, audio_received_at=audio_received_at)

    def run_voice_cycle(
        self,
        mock_command_text: Optional[str] = None,
        wake_detected_at: Optional[float] = None,
        audio_received_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Executes the voice cycle:
        IDLE -> LISTENING -> "Sim?" -> Capture -> STT -> ToolResolver -> PlanExecutor -> TTS -> IDLE.
        """
        if self._is_cycle_active:
            kon_logger.warning("[VOICE] Ciclo já em andamento. Ignorando novo gatilho.")
            return {"success": False, "message": "Ciclo de voz ocupado."}

        self._is_cycle_active = True
        self.loop_guard.reset()

        try:
            # 1. State: LISTENING (OUVINDO)
            # Immediately pause/stop wake word audio capture so the microphone is 100% free
            # and cannot capture the assistant's own TTS "Sim?" through the speakers
            self.audio_capture.stop()
            self.audio_capture.clear_queue()
            self.set_state(AssistantState.LISTENING, reason="Ativação detectada")

            # 2. TTS: "Sim?" while mic is completely closed
            t_tts_req = time.time()
            now_str = time.strftime("%H:%M:%S") + f".{int((t_tts_req % 1) * 1000):03d}"
            kon_logger.info(f'[{now_str}] [TTS] "Sim?" solicitado (microfone isolado)')

            sim_done = threading.Event()
            self.tts.falar("Sim?", on_complete=lambda: sim_done.set())
            sim_done.wait(timeout=3.0)

            # Settle window: let speaker reverberation dissipate before opening microphone
            time.sleep(0.15)

            command_text = ""
            t_capture_duration = 0.0
            t_stt_duration = 0.0
            t_plan_duration = 0.0

            if mock_command_text:
                kon_logger.info(f'[STT] Usando comando MOCK: "{mock_command_text}"')
                command_text = mock_command_text
                time.sleep(0.1)
            else:
                # 3. SpeechRecognitionEngine opens sr.Microphone() with PyAudio exclusively
                t_rec_start = time.time()
                now_str = time.strftime("%H:%M:%S") + f".{int((t_rec_start % 1) * 1000):03d}"
                kon_logger.info(f"[{now_str}] [CAPTURE] Ouvindo comando de voz via SpeechRecognition pt-BR...")

                if hasattr(self.stt, "listen_and_transcribe"):
                    command_text = self.stt.listen_and_transcribe(timeout=5, phrase_time_limit=8)
                    t_capture_duration = getattr(self.stt, "last_listen_duration", 0.0)
                    t_stt_duration = getattr(self.stt, "last_recognition_latency", time.time() - t_rec_start)
                else:
                    audio_array = self.command_capture.capture_command(max_duration=4.5)
                    t_capture_duration = time.time() - t_rec_start
                    if len(audio_array) > 0:
                        t_inf_start = time.time()
                        command_text = self.stt.transcribe(audio_array, language="pt")
                        t_stt_duration = time.time() - t_inf_start

            if not command_text or not command_text.strip():
                kon_logger.info("[VOICE] Nenhuma fala reconhecida.")
                self.set_state(AssistantState.IDLE, reason="Nenhum comando reconhecido")
                return {"success": False, "message": "Nenhum comando detectado."}

            # 5. Tool Resolver / Planner
            self.set_state(AssistantState.THINKING, reason="Planejando ações com ToolResolver")
            t_plan_start = time.time()
            plan: ToolPlan = self.tool_resolver.resolve(command_text)
            t_plan_duration = time.time() - t_plan_start
            kon_logger.info(f"[PLANNER] Plano gerado com {len(plan.steps)} passo(s) em {t_plan_duration*1000.0:.1f}ms")

            # 6. Execute Plan via PlanExecutor and ToolRegistry
            self.set_state(AssistantState.EXECUTING, reason="Executando ferramentas do plano")
            exec_result = self.plan_executor.execute_plan(plan)
            response_speech = exec_result.get("message", "Comando processado.")

            # Record in persistent SQLite history
            self.memory.log_command(
                command=command_text,
                state=AssistantState.EXECUTING.value,
                status="SUCCESS" if exec_result.get("success") else "FAILURE",
                response=response_speech,
            )

            # 7. TTS speaks response (State: SPEAKING)
            self.set_state(AssistantState.SPEAKING, reason="Falando resposta ao usuário")
            speech_done = threading.Event()
            self.tts.falar(response_speech, on_complete=lambda: speech_done.set())
            speech_done.wait(timeout=6.0)

            # Benchmark Metrics Logging
            t_ref = wake_detected_at or t_tts_req
            t_total_cycle = time.time() - t_ref
            kon_logger.info("=" * 60)
            kon_logger.info("           [BENCHMARK] MÉTRICAS DO CICLO")
            kon_logger.info("=" * 60)
            kon_logger.info(f"[BENCHMARK] A) Captura do comando: {t_capture_duration:.2f}s")
            kon_logger.info(f"[BENCHMARK] B) Transcrição STT (Whisper): {t_stt_duration:.2f}s")
            kon_logger.info(f"[BENCHMARK] C) Resolução do Plano: {t_plan_duration*1000.0:.1f}ms")
            kon_logger.info(f"[BENCHMARK] D) Tempo total do ciclo: {t_total_cycle:.2f}s")
            kon_logger.info("=" * 60)

            # 8. Return to IDLE
            self.set_state(AssistantState.IDLE, reason="Ciclo de voz finalizado com sucesso")
            kon_logger.info("[VOICE] Ciclo de voz concluído com sucesso. Retornando ao IDLE.")

            first_tool = plan.steps[0].tool if plan.steps else "unknown"
            canonical_intent = first_tool
            if first_tool == "open_application" and plan.steps and plan.steps[0].arguments.get("application") == "chrome":
                canonical_intent = "abrir_navegador"
            elif first_tool == "open_folder":
                canonical_intent = "abrir_pasta"
            elif first_tool == "system_info":
                metric = plan.steps[0].arguments.get("metric", "") if plan.steps else ""
                if metric in ("time", "hora", "horas"):
                    canonical_intent = "informar_horario"
                else:
                    canonical_intent = "system_status"

            return {
                "success": exec_result.get("success", True),
                "command": command_text,
                "intent": {"intent": canonical_intent, "tool": first_tool},
                "plan": [s.__dict__ for s in plan.steps],
                "result": exec_result,
                "response": response_speech,
            }



        except Exception as exc:
            kon_logger.error(f"[VOICE] Erro crítico no ciclo de voz: {exc}")
            self.set_state(AssistantState.ERROR, reason=str(exc))
            self.tts.falar("Ocorreu um erro no processamento.")
            time.sleep(1.0)
            self.set_state(AssistantState.IDLE, reason="Recuperado de erro")
            return {"success": False, "error": str(exc)}

        finally:
            self._is_cycle_active = False
            self.audio_capture.clear_queue()
            # Reset activation sources to prevent acoustic re-triggers
            if hasattr(self.activation_manager, "clap_source") and self.activation_manager.clap_source:
                self.activation_manager.clap_source.reset()
            if hasattr(self.wake_detector, "_last_trigger_time"):
                self.wake_detector._last_trigger_time = time.time() + 0.5  # 500ms cooldown
            # Reopen continuous PyAudio capture stream only when returning to IDLE
            time.sleep(0.1)
            self.audio_capture.clear_queue()
            if self._is_running:
                self.audio_capture.start()
