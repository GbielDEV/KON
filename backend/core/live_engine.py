"""
KON Live Audio & Agent Engine (ADA V2 Blueprint).
Direct integration with Google Gemini Live API using Native Audio full-duplex streaming,
real-time tool calling, instantaneous barge-in, resilient reconnection, and audio telemetry.
"""
from __future__ import annotations

import asyncio
import os
import time
import math
import struct
import json
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

import pyaudio
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.core.logger import kon_logger
from backend.ai.gemini_tools import GeminiToolDispatcher
from backend.core.state import AssistantState

load_dotenv()

# Audio Specifications (ADA V2 Standard)
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL_NAME = "models/gemini-2.5-flash-native-audio-preview-12-2025"

KON_SYSTEM_INSTRUCTION = (
    "Você é o KON, um assistente pessoal e agente de computador de alta performance para o sistema Windows. "
    "Sua identidade é moderna, tecnológica, direta, ágil e prestativa. "
    "Você se comunica em português brasileiro com frases completas, concisas e ritmo dinâmico. "
    "Você possui capacidade total de operar o Windows através das ferramentas (Function Calling): "
    "abrir e fechar aplicativos (Chrome, Bloco de Notas, Calculadora, VS Code, Terminal), "
    "gerenciar arquivos e pastas (pesquisar, abrir, listar, criar, copiar, mover, excluir com segurança), "
    "navegar na internet e gerenciar abas de navegador (abrir abas, alternar, fechar, navegar para URLs), "
    "e interagir com interfaces gráficas reais (observar a tela e janelas ativas, mover mouse, clicar, duplo clique, "
    "clique direito, digitar texto, pressionar teclas, atalhos, rolar a tela). "
    "Princípio de Computer Use: observe o estado da interface (observe_ui, get_active_window) antes de agir por coordenadas. "
    "Quando o usuário solicitar uma tarefa com múltiplas etapas, execute com segurança e autonomia. "
    "Ações de alto impacto como excluir arquivos ou desligar o sistema possuem verificação de segurança automática e "
    "requerem confirmação por voz do usuário. Ao receber o resultado de uma ferramenta, comunique o status de forma natural e concisa. "
    "Nunca exponha seu raciocínio interno ou pensamentos privados; responda sempre de forma operacional e natural."
)


class LiveAudioTelemetry:
    """Telemetry tracker for detailed audio and tool invocation latency diagnostics."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.t_speech_start: Optional[float] = None
        self.t_first_audio_sent: Optional[float] = None
        self.t_user_transcription: Optional[float] = None
        self.t_first_response: Optional[float] = None
        self.t_first_audio_recv: Optional[float] = None
        self.t_speaker_start: Optional[float] = None
        self.t_tool_call_recv: Optional[float] = None
        self.t_tool_exec_duration: Optional[float] = None
        self.t_tool_response_sent: Optional[float] = None
        self.t_post_tool_audio_recv: Optional[float] = None
        self.t_turn_complete: Optional[float] = None
        self.tool_names: List[str] = []

    def log_summary(self) -> None:
        t0 = self.t_speech_start or self.t_first_audio_sent
        if not t0:
            return

        lines = ["[TELEMETRY] --- Resumo de Latência do Turno ---"]
        if self.t_first_response:
            lines.append(f"  • Fala -> Primeira Resposta: {(self.t_first_response - t0)*1000:.1f}ms")
        if self.t_first_audio_recv:
            lines.append(f"  • Fala -> Primeiro Áudio (Gemini): {(self.t_first_audio_recv - t0)*1000:.1f}ms")
        if self.t_speaker_start and self.t_first_audio_recv:
            lines.append(f"  • Resposta -> Áudio no Speaker: {(self.t_speaker_start - self.t_first_audio_recv)*1000:.1f}ms")
        if self.t_tool_call_recv:
            lines.append(f"  • Fala -> Function Call ({', '.join(self.tool_names)}): {(self.t_tool_call_recv - t0)*1000:.1f}ms")
        if self.t_tool_exec_duration is not None:
            lines.append(f"  • Execução da Ferramenta: {self.t_tool_exec_duration*1000:.1f}ms")
        if self.t_post_tool_audio_recv and self.t_tool_response_sent:
            lines.append(f"  • Retorno da Ferramenta -> Resposta de Áudio: {(self.t_post_tool_audio_recv - self.t_tool_response_sent)*1000:.1f}ms")
        if self.t_turn_complete:
            lines.append(f"  • Duração Total do Turno: {(self.t_turn_complete - t0):.2f}s")
        kon_logger.info("\n".join(lines))


class LiveAudioEngine:
    """
    Core Gemini Live Engine based on ADA V2 AudioLoop architecture.
    Manages bidirectional streaming audio, tool calling, barge-in, and reconnection.
    """

    def __init__(
        self,
        tool_dispatcher: Optional[GeminiToolDispatcher] = None,
        on_state_change: Optional[Callable[[AssistantState, str], None]] = None,
        on_transcription: Optional[Callable[[Dict[str, str]], None]] = None,
        on_audio_levels: Optional[Callable[[float, float], None]] = None,
        on_tool_executing: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        input_device_index: Optional[int] = None,
        input_device_name: Optional[str] = None,
        output_device_index: Optional[int] = None,
        voice_name: str = "Kore",
        history_dir: Optional[Path] = None,
    ) -> None:
        self.tool_dispatcher = tool_dispatcher or GeminiToolDispatcher()
        self.on_state_change = on_state_change
        self.on_transcription = on_transcription
        self.on_audio_levels = on_audio_levels
        self.on_tool_executing = on_tool_executing
        self.on_error = on_error

        self.input_device_index = input_device_index
        self.input_device_name = input_device_name
        self.output_device_index = output_device_index
        self.voice_name = voice_name

        self.history_dir = history_dir or Path("data/chat_history")
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.history_dir / "live_chat.jsonl"

        self.pya = pyaudio.PyAudio()
        self.session = None
        self.audio_in_queue: Optional[asyncio.Queue] = None
        self.out_queue: Optional[asyncio.Queue] = None

        self.stop_event = asyncio.Event()
        self.paused = False

        self._last_input_transcription = ""
        self._last_output_transcription = ""
        self._is_speaking = False
        self._is_model_speaking = False

        self.telemetry = LiveAudioTelemetry()

        # Build GenAI Client
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            kon_logger.error("[LIVE_ENGINE] GEMINI_API_KEY não encontrada no ambiente!")
        self.client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key
        )

    def _set_state(self, state: AssistantState, desc: str = "") -> None:
        if self.on_state_change:
            try:
                self.on_state_change(state, desc)
            except Exception as e:
                kon_logger.debug(f"[ENGINE] Erro em on_state_change callback: {e}")

    def stop(self) -> None:
        kon_logger.info("[LIVE_ENGINE] Sinal de parada acionado.")
        self.stop_event.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        kon_logger.info(f"[LIVE_ENGINE] Áudio pausado: {paused}")

    def clear_audio_queue(self) -> None:
        """Instantaneous Barge-in: Drops all buffered audio chunks to silence the output immediately."""
        count = 0
        if self.audio_in_queue:
            while not self.audio_in_queue.empty():
                try:
                    self.audio_in_queue.get_nowait()
                    count += 1
                except asyncio.QueueEmpty:
                    break
        if count > 0:
            kon_logger.info(f"[BARGE-IN] {count} chunks de áudio descartados imediatamente. Interrupção do usuário.")
        self._is_model_speaking = False

    def log_chat(self, sender: str, text: str) -> None:
        """Persists chat history turn for context continuity."""
        try:
            entry = {"timestamp": time.time(), "sender": sender, "text": text}
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            kon_logger.debug(f"[LIVE_ENGINE] Erro ao salvar histórico de chat: {e}")

    def get_recent_history(self, limit: int = 6) -> List[Dict[str, Any]]:
        """Reads recent conversation turns."""
        if not self.history_file.exists():
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            history = []
            for line in lines[-limit:]:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return history
        except Exception as e:
            kon_logger.debug(f"[LIVE_ENGINE] Erro ao carregar histórico: {e}")
            return []

    async def send_realtime(self) -> None:
        """Background task sending microphone chunks from out_queue to Gemini Live via low-latency realtime API."""
        while not self.stop_event.is_set():
            try:
                msg = await self.out_queue.get()
                if self.session:
                    if self.telemetry.t_first_audio_sent is None:
                        self.telemetry.t_first_audio_sent = time.time()
                    await self.session.send_realtime_input(audio=msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                kon_logger.error(f"[LIVE_ENGINE] Erro no send_realtime: {e}")
                await asyncio.sleep(0.05)

    async def listen_audio(self) -> None:
        """Background task capturing PCM chunks from microphone and queuing to Gemini."""
        mic_info = self.pya.get_default_input_device_info()
        device_index = self.input_device_index if self.input_device_index is not None else mic_info["index"]

        try:
            audio_stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            kon_logger.info(f"[LIVE_ENGINE] Microfone ativo: '{mic_info['name']}' (Index: {device_index}, 16kHz, mono)")
        except OSError as e:
            kon_logger.error(f"[LIVE_ENGINE] Falha ao abrir microfone: {e}")
            if self.on_error:
                self.on_error(f"Erro no microfone: {e}")
            return

        try:
            while not self.stop_event.is_set():
                if self.paused:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    data = await asyncio.to_thread(audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)

                    # Compute RMS volume level for UI Hologram visualizer and speech detection
                    count = len(data) // 2
                    if count > 0:
                        shorts = struct.unpack(f"<{count}h", data)
                        sum_squares = sum(s ** 2 for s in shorts)
                        rms = int(math.sqrt(sum_squares / count))
                    else:
                        rms = 0

                    # Mark speech start timestamp for latency telemetry
                    if rms > 300 and self.telemetry.t_speech_start is None:
                        self.telemetry.t_speech_start = time.time()

                    if self.on_audio_levels:
                        # Normalize rms (approx 0-3000 to 0.0-1.0)
                        norm_input = min(1.0, rms / 2500.0)
                        norm_output = 1.0 if self._is_model_speaking else 0.0
                        self.on_audio_levels(norm_input, norm_output)

                    # Send audio to Gemini Live queue with non-blocking overflow protection
                    if self.out_queue:
                        chunk_msg = {"data": data, "mime_type": "audio/pcm"}
                        try:
                            self.out_queue.put_nowait(chunk_msg)
                        except asyncio.QueueFull:
                            # Drop oldest chunk to maintain strict real-time delivery
                            try:
                                self.out_queue.get_nowait()
                                self.out_queue.put_nowait(chunk_msg)
                            except Exception:
                                pass

                except asyncio.CancelledError:
                    break
                except Exception as read_err:
                    kon_logger.debug(f"[LIVE_ENGINE] Erro na leitura de áudio: {read_err}")
                    await asyncio.sleep(0.05)

        finally:
            try:
                audio_stream.stop_stream()
                audio_stream.close()
            except Exception:
                pass

    async def play_audio(self) -> None:
        """Background task consuming PCM chunks from audio_in_queue and playing via speaker."""
        default_out = self.pya.get_default_output_device_info()
        out_index = self.output_device_index if self.output_device_index is not None else default_out["index"]

        try:
            stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE,
                output=True,
                output_device_index=out_index,
            )
            kon_logger.info(f"[LIVE_ENGINE] Alto-falante ativo: '{default_out['name']}' (24kHz, mono)")
        except OSError as e:
            kon_logger.error(f"[LIVE_ENGINE] Falha ao abrir dispositivo de saída de áudio: {e}")
            return

        try:
            while not self.stop_event.is_set():
                bytestream = await self.audio_in_queue.get()
                if self.telemetry.t_speaker_start is None:
                    self.telemetry.t_speaker_start = time.time()

                self._is_model_speaking = True
                self._set_state(AssistantState.SPEAKING, "KON está falando")
                await asyncio.to_thread(stream.write, bytestream)

                if self.audio_in_queue.empty():
                    self._is_model_speaking = False
                    self._set_state(AssistantState.IDLE, "KON está pronto e ouvindo")

        except asyncio.CancelledError:
            pass
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

    async def receive_audio(self) -> None:
        """
        Background task consuming events from Gemini Live session:
        Handles Native Audio PCM chunks, transcription deltas, and tool calls.
        """
        try:
            while not self.stop_event.is_set():
                turn = self.session.receive()
                async for response in turn:
                    # 1. Server Content (Native Audio, Text, Thought, Transcriptions)
                    if response.server_content:
                        if self.telemetry.t_first_response is None:
                            self.telemetry.t_first_response = time.time()

                        # User transcription -> Barge-in & UI streaming
                        if response.server_content.input_transcription:
                            transcript = response.server_content.input_transcription.text
                            if transcript and transcript != self._last_input_transcription:
                                if self.telemetry.t_user_transcription is None:
                                    self.telemetry.t_user_transcription = time.time()
                                delta = transcript
                                if transcript.startswith(self._last_input_transcription):
                                    delta = transcript[len(self._last_input_transcription):]
                                self._last_input_transcription = transcript

                                if delta:
                                    # BARGE-IN: User is speaking, drop queued model audio immediately
                                    self.clear_audio_queue()
                                    self._set_state(AssistantState.LISTENING, "Ouvindo você...")

                                    if self.on_transcription:
                                        self.on_transcription({"sender": "User", "text": delta})

                        # Model turn parts: process Native Audio PCM directly and discard internal thoughts
                        if response.server_content.model_turn:
                            for part in response.server_content.model_turn.parts:
                                # A. Ignore model internal reasoning thoughts completely
                                if getattr(part, "thought", False):
                                    continue

                                # B. Native Audio PCM Chunks (Extracted directly without calling response.data)
                                if part.inline_data and isinstance(part.inline_data.data, bytes):
                                    audio_bytes = part.inline_data.data
                                    if len(audio_bytes) > 0:
                                        if self.telemetry.t_first_audio_recv is None:
                                            self.telemetry.t_first_audio_recv = time.time()
                                        if self.telemetry.t_tool_response_sent and self.telemetry.t_post_tool_audio_recv is None:
                                            self.telemetry.t_post_tool_audio_recv = time.time()
                                        self.audio_in_queue.put_nowait(audio_bytes)

                        # Model transcription (output_transcription)
                        if response.server_content.output_transcription:
                            transcript = response.server_content.output_transcription.text
                            if transcript and transcript != self._last_output_transcription:
                                delta = transcript
                                if transcript.startswith(self._last_output_transcription):
                                    delta = transcript[len(self._last_output_transcription):]
                                self._last_output_transcription = transcript

                                if delta:
                                    if self.on_transcription:
                                        self.on_transcription({"sender": "KON", "text": delta})

                        if response.server_content.turn_complete:
                            self.telemetry.t_turn_complete = time.time()
                            self.telemetry.log_summary()
                            self.telemetry.reset()

                    # 2. Tool Calls (Autonomous Agent Execution)
                    if response.tool_call:
                        fc_names = [fc.name for fc in response.tool_call.function_calls]
                        kon_logger.info(f"[LIVE_ENGINE] Tool calls recebidas do Gemini: {fc_names}")
                        self.telemetry.t_tool_call_recv = time.time()
                        self.telemetry.tool_names = fc_names
                        self._set_state(AssistantState.THINKING, "Processando solicitação...")

                        # Execute all function calls in batch using dispatcher
                        t_tool_start = time.time()
                        function_responses = await self.tool_dispatcher.execute_function_calls(
                            response.tool_call.function_calls
                        )
                        self.telemetry.t_tool_exec_duration = time.time() - t_tool_start

                        # Return function responses back to Gemini Live
                        if function_responses:
                            self.telemetry.t_tool_response_sent = time.time()
                            kon_logger.info(f"[LIVE_ENGINE] Enviando {len(function_responses)} respostas de ferramentas de volta ao Gemini...")
                            await self.session.send_tool_response(function_responses=function_responses)

                # Reset deltas for next turn
                self._last_input_transcription = ""
                self._last_output_transcription = ""

        except asyncio.CancelledError:
            kon_logger.info("[LIVE_ENGINE] receive_audio cancelado.")
            raise
        except Exception as e:
            kon_logger.error(f"[LIVE_ENGINE] Erro crítico em receive_audio: {e}")
            raise e

    async def run(self) -> None:
        """
        Main run loop with exponential backoff reconnection.
        Replicates ADA V2 resilience architecture.
        """
        retry_delay = 1.0
        is_reconnect = False

        while not self.stop_event.is_set():
            try:
                self._set_state(AssistantState.BOOT, "Conectando ao Gemini Live API...")
                kon_logger.info(f"[LIVE_ENGINE] Conectando à Gemini Live API (Modelo: {MODEL_NAME})...")

                # Setup Live Configuration
                tools_config = self.tool_dispatcher.get_gemini_tools_config()
                config = types.LiveConnectConfig(
                    response_modalities=["AUDIO"],
                    output_audio_transcription={},
                    input_audio_transcription={},
                    system_instruction=KON_SYSTEM_INSTRUCTION,
                    tools=tools_config,
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self.voice_name
                            )
                        )
                    )
                )

                async with (
                    self.client.aio.live.connect(model=MODEL_NAME, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=100)

                    kon_logger.info("[LIVE_ENGINE] Sessão Gemini Live estabelecida com sucesso!")
                    self._set_state(AssistantState.IDLE, "Gemini Live ativo. Pode falar.")

                    # Spawn Streaming Subtasks
                    tg.create_task(self.send_realtime())
                    tg.create_task(self.listen_audio())
                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())

                    # Context restoration on reconnection
                    if is_reconnect:
                        history = self.get_recent_history(limit=4)
                        if history:
                            context_summary = "Notificação do Sistema: Conexão neural restabelecida. Histórico recente:\n"
                            for h in history:
                                context_summary += f"[{h.get('sender')}]: {h.get('text')}\n"
                            context_summary += "Retome a conversa normalmente com o usuário."
                            await self.session.send(input=context_summary, end_of_turn=True)

                    retry_delay = 1.0
                    await self.stop_event.wait()

            except asyncio.CancelledError:
                kon_logger.info("[LIVE_ENGINE] Loop principal cancelado.")
                break

            except Exception as exc:
                kon_logger.error(f"[LIVE_ENGINE] Erro na sessão Live: {exc}")
                self._set_state(AssistantState.ERROR, f"Erro de conexão: {exc}")

                if self.stop_event.is_set():
                    break

                kon_logger.info(f"[LIVE_ENGINE] Tentando reconectar em {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)
                is_reconnect = True

        self.pya.terminate()
        kon_logger.info("[LIVE_ENGINE] Motor de áudio finalizado.")

