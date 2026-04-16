from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from duplex_bot.adapters.base import TelephonyAdapter
from duplex_bot.config import AppConfig
from duplex_bot.core.audio import resample_pcm, split_pcm_chunks
from duplex_bot.core.conversation import ConversationHistory
from duplex_bot.core.events import (
    AudioChunk,
    ControlEvent,
    FunctionCallRequest,
    FunctionCallResult,
    InterruptSignal,
    LLMResponseChunk,
    SpeechSegment,
    TTSAudioChunk,
    ToolCallFragment,
)
from duplex_bot.core.pipeline import accumulate_sentences
from duplex_bot.llm.base import LLMBase
from duplex_bot.llm.function_calling import FunctionExecutor, FunctionRegistry
from duplex_bot.llm.turn_detector import TurnDetector
from duplex_bot.observability.tracer import SessionTracer
from duplex_bot.stt.base import STTBase
from duplex_bot.strategies.noise_filter import NoiseFilter
from duplex_bot.strategies.truncation import TruncationTracker
from duplex_bot.tts.base import TTSBase
from duplex_bot.vad.stream import VADStream, SpeechEnded, SpeechStarted

logger = logging.getLogger(__name__)


class VoiceSession:
    """Per-connection orchestrator that wires the full pipeline.

    Each WebSocket connection creates one VoiceSession that owns:
    - All asyncio queues connecting pipeline stages
    - All concurrent pipeline tasks
    - Conversation history and state
    - Interrupt handling and auto-truncation
    """

    def __init__(
        self,
        session_id: str,
        adapter: TelephonyAdapter,
        vad_stream: VADStream,
        stt: STTBase,
        llm: LLMBase,
        tts: TTSBase,
        config: AppConfig,
        function_registry: FunctionRegistry | None = None,
        tracer: SessionTracer | None = None,
    ):
        self.session_id = session_id
        self._adapter = adapter
        self._vad_stream = vad_stream
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._config = config
        self._tracer = tracer

        # Queues
        self._audio_in_q: asyncio.Queue[AudioChunk] = asyncio.Queue(maxsize=100)
        self._speech_q: asyncio.Queue[SpeechSegment] = asyncio.Queue()
        self._transcript_q: asyncio.Queue[str] = asyncio.Queue()
        self._tts_text_q: asyncio.Queue[str] = asyncio.Queue()
        self._interrupt_q: asyncio.Queue[InterruptSignal] = asyncio.Queue()
        self._function_result_q: asyncio.Queue[FunctionCallResult] = asyncio.Queue()

        # State
        self._conversation = ConversationHistory(config.system_prompt)
        self._turn_detector = TurnDetector(llm, config.eot)
        self._noise_filter = NoiseFilter()
        self._truncation = TruncationTracker()
        self._function_executor = FunctionExecutor(function_registry or FunctionRegistry())

        # Control
        self._tasks: list[asyncio.Task] = []
        self._is_agent_speaking = False
        self._current_llm_task: asyncio.Task | None = None
        self._current_tts_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        # Timing for EIBC→FSB
        self._input_committed_at_ms: float = 0
        self._websocket: WebSocket | None = None

    async def run(self, websocket: WebSocket) -> None:
        """Main entry point. Starts all pipeline tasks and runs until disconnect."""
        self._websocket = websocket
        metadata = await self._adapter.on_connect(websocket)
        if metadata.session_id:
            self.session_id = metadata.session_id

        if self._tracer:
            self._tracer.start_session(
                self.session_id,
                self._adapter.name,
                metadata.extra,
            )

        logger.info("Session %s started (adapter=%s)", self.session_id, self._adapter.name)

        self._tasks = [
            asyncio.create_task(self._inbound_loop(websocket), name="inbound"),
            asyncio.create_task(self._vad_loop(), name="vad"),
            asyncio.create_task(self._stt_loop(), name="stt"),
            asyncio.create_task(self._turn_gate_loop(), name="turn_gate"),
            asyncio.create_task(self._tts_loop(websocket), name="tts"),
            asyncio.create_task(self._interrupt_handler(websocket), name="interrupt"),
            asyncio.create_task(self._function_result_loop(), name="func_result"),
        ]

        try:
            # Wait for any task to complete (usually means disconnection or error)
            done, _ = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                    logger.error(
                        "Task %s failed: %s",
                        task.get_name(),
                        task.exception(),
                    )
        except Exception:
            logger.exception("Session %s error", self.session_id)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Cancel all tasks and clean up."""
        self._shutdown_event.set()
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._tracer:
            self._tracer.end_session(
                turn_count=self._conversation.turn_count,
                barge_in_count=self._truncation.barge_in_count,
            )

        logger.info("Session %s shut down", self.session_id)

    # ─── Pipeline Loops ─────────────────────────────────────────────

    async def _inbound_loop(self, websocket: WebSocket) -> None:
        """Read messages from WebSocket and route to appropriate queues."""
        try:
            while not self._shutdown_event.is_set():
                event = await self._adapter.receive(websocket)

                if isinstance(event, AudioChunk):
                    event.session_id = self.session_id
                    # Resample to internal rate if needed
                    if event.sample_rate != self._config.internal_sample_rate:
                        event.data = resample_pcm(
                            event.data,
                            event.sample_rate,
                            self._config.internal_sample_rate,
                        )
                        event.sample_rate = self._config.internal_sample_rate

                    # Split into VAD-sized chunks
                    chunk_size_bytes = int(
                        self._config.internal_sample_rate * 2 * self._config.vad.chunk_size_ms / 1000
                    )
                    for i in range(0, len(event.data), chunk_size_bytes):
                        chunk_data = event.data[i : i + chunk_size_bytes]
                        if len(chunk_data) == chunk_size_bytes:
                            chunk = AudioChunk(
                                data=chunk_data,
                                sample_rate=self._config.internal_sample_rate,
                                session_id=self.session_id,
                            )
                            try:
                                self._audio_in_q.put_nowait(chunk)
                            except asyncio.QueueFull:
                                pass  # Drop oldest audio on overload

                elif isinstance(event, ControlEvent):
                    if event.event_type == "stop":
                        logger.info("Session %s: stop event received", self.session_id)
                        return
                    if event.event_type == "mark":
                        self._truncation.on_mark_received(event.data.get("name", ""))

        except WebSocketDisconnect:
            logger.info("Session %s: WebSocket disconnected", self.session_id)
        except Exception:
            logger.exception("Inbound loop error")

    async def _vad_loop(self) -> None:
        """Process audio chunks through VAD and emit speech events."""
        try:
            while not self._shutdown_event.is_set():
                chunk = await self._audio_in_q.get()

                span = self._tracer.start_span("vad") if self._tracer else None
                vad_event = await self._vad_stream.process(chunk)

                if isinstance(vad_event, SpeechStarted):
                    # Emit interrupt signal for barge-in
                    if self._is_agent_speaking:
                        vad_event.interrupt.session_id = self.session_id
                        vad_event.interrupt.playback_position_ms = (
                            self._truncation.current_playback_ms
                        )
                        await self._interrupt_q.put(vad_event.interrupt)

                elif isinstance(vad_event, SpeechEnded):
                    vad_event.segment.session_id = self.session_id
                    self._input_committed_at_ms = time.monotonic() * 1000
                    await self._speech_q.put(vad_event.segment)

                if span and self._tracer:
                    self._tracer.end_span("vad", {
                        "is_speech": isinstance(vad_event, (SpeechStarted, SpeechEnded)),
                        "vad_state": self._vad_stream.state.name,
                    })

        except asyncio.CancelledError:
            pass

    async def _stt_loop(self) -> None:
        """Transcribe speech segments via STT."""
        try:
            while not self._shutdown_event.is_set():
                segment = await self._speech_q.get()

                span_id = None
                if self._tracer:
                    span_id = self._tracer.start_span("stt")

                stt_start = time.monotonic() * 1000
                transcript = await self._stt.transcribe(
                    segment.audio,
                    segment.sample_rate,
                    self._config.azure_stt.language,
                )
                stt_latency = time.monotonic() * 1000 - stt_start

                if self._tracer:
                    self._tracer.end_span("stt", {
                        "stt_latency_ms": stt_latency,
                        "stt_confidence": transcript.confidence,
                        "text": transcript.text,
                    })

                if transcript.text.strip():
                    # Apply noise filter
                    if self._noise_filter.is_meaningful(transcript.text):
                        logger.info("STT: '%s' (%.0fms)", transcript.text, stt_latency)
                        await self._transcript_q.put(transcript.text)

                        # Send transcript to client UI
                        if self._websocket:
                            await self._adapter.send_text(
                                self._websocket, "transcript", transcript.text
                            )
                    else:
                        logger.debug("STT filtered as noise: '%s'", transcript.text)

        except asyncio.CancelledError:
            pass

    async def _turn_gate_loop(self) -> None:
        """Accumulate transcripts and detect end-of-turn to trigger LLM."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    text = await asyncio.wait_for(
                        self._transcript_q.get(), timeout=0.1
                    )
                    self._turn_detector.add_transcript(text)
                except asyncio.TimeoutError:
                    pass

                # Check end of turn
                accumulated = self._turn_detector.get_accumulated_text()
                if not accumulated:
                    continue

                # Calculate silence duration since last transcript
                silence_ms = time.monotonic() * 1000 - (
                    self._turn_detector._last_transcript_time or time.monotonic() * 1000
                )

                is_done = await self._turn_detector.check_end_of_turn(
                    silence_ms,
                    self._conversation.get_context(),
                )

                if is_done:
                    user_text = self._turn_detector.get_accumulated_text()
                    self._turn_detector.reset()

                    logger.info("Turn complete: '%s'", user_text)
                    self._conversation.add_user_message(user_text)

                    if self._tracer:
                        self._tracer.record_event("user_turn", {
                            "text": user_text,
                            "turn_count": self._conversation.turn_count,
                        })

                    # Trigger LLM generation
                    await self._generate_response()

        except asyncio.CancelledError:
            pass

    async def _generate_response(self) -> None:
        """Generate LLM response and stream to TTS."""
        # Cancel any previous in-progress generation
        if self._current_llm_task and not self._current_llm_task.done():
            self._current_llm_task.cancel()

        self._current_llm_task = asyncio.create_task(self._llm_generate())

    async def _llm_generate(self) -> None:
        """Stream LLM response, split into sentences, push to TTS queue."""
        messages = self._conversation.get_messages()
        tools = self._function_executor._registry.tool_schemas if self._function_executor._registry.has_tools else None

        span_id = None
        if self._tracer:
            span_id = self._tracer.start_span("llm")

        llm_start = time.monotonic() * 1000
        first_token_at: float | None = None
        full_response = ""
        sentence_buffer = ""
        tool_calls: list[ToolCallFragment] = []

        try:
            async for chunk in self._llm.generate_stream(messages, tools):
                if first_token_at is None and chunk.text:
                    first_token_at = time.monotonic() * 1000

                if chunk.text:
                    full_response += chunk.text
                    # Accumulate and extract complete sentences
                    sentences, sentence_buffer = accumulate_sentences(
                        sentence_buffer, chunk.text
                    )
                    for sentence in sentences:
                        await self._tts_text_q.put(sentence)

                if chunk.is_final:
                    # Flush remaining buffer
                    if sentence_buffer.strip():
                        await self._tts_text_q.put(sentence_buffer.strip())
                        sentence_buffer = ""

                    if chunk.tool_calls:
                        tool_calls = chunk.tool_calls

                    # Signal TTS that this response is done
                    await self._tts_text_q.put("")  # Empty string = done marker

        except asyncio.CancelledError:
            logger.debug("LLM generation cancelled (barge-in)")
            await self._tts_text_q.put("")  # Ensure TTS gets done marker
            raise

        llm_total = time.monotonic() * 1000 - llm_start
        llm_ttft = (first_token_at - llm_start) if first_token_at else 0

        # Record assistant response
        if full_response:
            self._conversation.add_assistant_message(full_response)

            # Send agent text to client UI
            if self._websocket:
                await self._adapter.send_text(
                    self._websocket, "agent_text", full_response
                )

        if self._tracer:
            self._tracer.end_span("llm", {
                "llm_ttft_ms": llm_ttft,
                "llm_total_latency_ms": llm_total,
                "llm_model": self._config.llm.model,
                "agent_response_full": full_response,
            })
            self._tracer.record_generation(
                model=self._config.llm.model,
                input_messages=messages,
                output=full_response,
            )

        # Handle tool calls
        if tool_calls:
            for tc in tool_calls:
                try:
                    args = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                self._conversation.add_tool_call(tc.id, tc.name, tc.arguments)

                request = FunctionCallRequest(
                    call_id=tc.id,
                    name=tc.name,
                    arguments=args,
                    session_id=self.session_id,
                )
                # Fire-and-forget: result comes back via _function_result_loop
                task = self._function_executor.execute_async(request)
                task.add_done_callback(
                    lambda t: asyncio.get_event_loop().call_soon_threadsafe(
                        self._function_result_q.put_nowait,
                        t.result() if not t.cancelled() and not t.exception() else None,
                    )
                )

    async def _tts_loop(self, websocket: WebSocket) -> None:
        """Read sentences from TTS queue, synthesize, and send audio."""
        try:
            while not self._shutdown_event.is_set():
                text = await self._tts_text_q.get()

                if not text:
                    # Done marker — end of response
                    self._is_agent_speaking = False
                    self._truncation.reset()
                    continue

                self._is_agent_speaking = True

                span_id = None
                if self._tracer:
                    span_id = self._tracer.start_span("tts")

                tts_start = time.monotonic() * 1000
                first_byte = True

                try:
                    async for audio_chunk in self._tts.synthesize_stream(text):
                        if first_byte:
                            tts_ttfb = time.monotonic() * 1000 - tts_start
                            first_byte = False

                            # Record EIBC→FSB if we have the committed timestamp
                            if self._input_committed_at_ms > 0:
                                eibc_to_fsb = time.monotonic() * 1000 - self._input_committed_at_ms
                                if self._tracer:
                                    self._tracer.record_event("eibc_to_fsb", {
                                        "eibc_to_fsb_ms": eibc_to_fsb,
                                    })
                                logger.info("EIBC→FSB: %.0fms", eibc_to_fsb)
                                self._input_committed_at_ms = 0

                        # Track for truncation
                        self._truncation.record_segment(
                            text, audio_chunk.cumulative_duration_ms
                        )

                        # Send to client
                        await self._adapter.send_audio(websocket, audio_chunk)

                except asyncio.CancelledError:
                    logger.debug("TTS cancelled (barge-in)")
                    raise

                if self._tracer and span_id:
                    self._tracer.end_span("tts", {
                        "tts_ttfb_ms": tts_ttfb if not first_byte else 0,
                        "tts_provider": self._config.tts_provider,
                        "text": text,
                    })

        except asyncio.CancelledError:
            pass

    async def _interrupt_handler(self, websocket: WebSocket) -> None:
        """Handle barge-in interrupts."""
        try:
            while not self._shutdown_event.is_set():
                interrupt = await self._interrupt_q.get()

                logger.info(
                    "Barge-in at playback=%.0fms",
                    interrupt.playback_position_ms,
                )

                if self._tracer:
                    self._tracer.record_event("barge_in", {
                        "playback_position_ms": interrupt.playback_position_ms,
                    })

                # 1. Send clear to client
                await self._adapter.send_clear(websocket)

                # 2. Cancel current LLM generation
                if self._current_llm_task and not self._current_llm_task.done():
                    self._current_llm_task.cancel()

                # 3. Drain TTS text queue
                while not self._tts_text_q.empty():
                    try:
                        self._tts_text_q.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                # 4. Auto-truncation: update conversation history
                heard_text = self._truncation.get_heard_text(
                    interrupt.playback_position_ms
                )
                if heard_text:
                    self._conversation.truncate_last_assistant(heard_text)
                    if self._tracer:
                        self._tracer.record_event("auto_truncation", {
                            "agent_response_heard": heard_text,
                        })

                # 5. Reset state
                self._is_agent_speaking = False
                self._truncation.reset()

                # NOTE: We do NOT cancel in-flight function calls

        except asyncio.CancelledError:
            pass

    async def _function_result_loop(self) -> None:
        """Process function call results and trigger follow-up LLM generation."""
        try:
            while not self._shutdown_event.is_set():
                result = await self._function_result_q.get()
                if result is None:
                    continue

                logger.info("Function %s result received", result.name)

                # Add to conversation
                if result.error:
                    self._conversation.add_function_result(
                        result.call_id, result.name,
                        json.dumps({"error": result.error}),
                    )
                else:
                    self._conversation.add_function_result(
                        result.call_id, result.name, result.result,
                    )

                # Trigger follow-up LLM generation
                await self._generate_response()

        except asyncio.CancelledError:
            pass
