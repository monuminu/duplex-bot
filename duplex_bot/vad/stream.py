from __future__ import annotations

import logging
import time
from collections import deque
from enum import Enum, auto

from duplex_bot.config import VADConfig
from duplex_bot.core.audio import pcm_duration_ms
from duplex_bot.core.events import AudioChunk, InterruptSignal, SpeechSegment
from duplex_bot.vad.base import VADBase

logger = logging.getLogger(__name__)


class VADState(Enum):
    IDLE = auto()
    SPEECH_STARTED = auto()
    SPEECH_ACTIVE = auto()
    SPEECH_ENDING = auto()


class VADStreamEvent:
    """Wrapper for events emitted by the VAD stream."""
    pass


class SpeechStarted(VADStreamEvent):
    """Emitted on speech onset — triggers interrupt."""
    def __init__(self, interrupt: InterruptSignal):
        self.interrupt = interrupt


class SpeechEnded(VADStreamEvent):
    """Emitted when speech segment is complete."""
    def __init__(self, segment: SpeechSegment):
        self.segment = segment


class VADStream:
    """State machine that wraps a VAD model and produces speech segments.

    States:
        IDLE → SPEECH_STARTED → SPEECH_ACTIVE → SPEECH_ENDING → IDLE

    On speech onset: emits SpeechStarted (contains InterruptSignal)
    On speech end: emits SpeechEnded (contains complete SpeechSegment)
    """

    def __init__(self, vad: VADBase, config: VADConfig, session_id: str = ""):
        self._vad = vad
        self._config = config
        self._session_id = session_id
        self._state = VADState.IDLE

        # Buffers
        self._prefix_buffer: deque[bytes] = deque()  # Ring buffer for prefix padding
        self._speech_buffer: list[bytes] = []

        # Timing
        self._speech_start_ms: float = 0
        self._speech_duration_ms: float = 0
        self._silence_duration_ms: float = 0

        # Calculate prefix buffer capacity (number of chunks)
        chunk_duration_ms = config.chunk_size_ms
        self._prefix_capacity = max(1, config.prefix_padding_ms // chunk_duration_ms)

    async def process(self, chunk: AudioChunk) -> VADStreamEvent | None:
        """Process an audio chunk and potentially emit a VAD event.

        Args:
            chunk: Audio chunk to process.

        Returns:
            A VADStreamEvent if a state transition occurred, None otherwise.
        """
        prob = await self._vad.process_chunk(chunk.data, chunk.sample_rate)
        chunk_ms = pcm_duration_ms(chunk.data, chunk.sample_rate)
        is_speech = prob >= self._config.activation_threshold

        if self._state == VADState.IDLE:
            # Keep a rolling prefix buffer
            self._prefix_buffer.append(chunk.data)
            if len(self._prefix_buffer) > self._prefix_capacity:
                self._prefix_buffer.popleft()

            if is_speech:
                self._state = VADState.SPEECH_STARTED
                self._speech_start_ms = time.monotonic() * 1000
                self._speech_duration_ms = chunk_ms
                self._silence_duration_ms = 0
                # Start speech buffer with prefix
                self._speech_buffer = list(self._prefix_buffer)
                self._speech_buffer.append(chunk.data)
                self._prefix_buffer.clear()

                logger.debug("VAD: IDLE → SPEECH_STARTED (prob=%.3f)", prob)
                return SpeechStarted(
                    InterruptSignal(session_id=self._session_id)
                )

        elif self._state == VADState.SPEECH_STARTED:
            self._speech_buffer.append(chunk.data)
            if is_speech:
                self._speech_duration_ms += chunk_ms
                if self._speech_duration_ms >= self._config.min_speech_duration_ms:
                    self._state = VADState.SPEECH_ACTIVE
                    logger.debug("VAD: SPEECH_STARTED → SPEECH_ACTIVE (%.0fms)", self._speech_duration_ms)
            else:
                # False alarm — back to idle
                self._state = VADState.IDLE
                self._speech_buffer.clear()
                self._speech_duration_ms = 0
                logger.debug("VAD: SPEECH_STARTED → IDLE (false alarm, prob=%.3f)", prob)

        elif self._state == VADState.SPEECH_ACTIVE:
            self._speech_buffer.append(chunk.data)
            if is_speech:
                self._speech_duration_ms += chunk_ms
                self._silence_duration_ms = 0
            else:
                self._silence_duration_ms += chunk_ms
                if self._silence_duration_ms >= self._config.min_silence_duration_ms:
                    self._state = VADState.SPEECH_ENDING
                    logger.debug("VAD: SPEECH_ACTIVE → SPEECH_ENDING (silence=%.0fms)", self._silence_duration_ms)
                    return self._emit_speech_segment()

        elif self._state == VADState.SPEECH_ENDING:
            # Already emitted, should not happen — reset
            self._reset_to_idle()

        return None

    def _emit_speech_segment(self) -> SpeechEnded:
        """Assemble the complete speech segment and reset state."""
        audio = b"".join(self._speech_buffer)
        duration = pcm_duration_ms(audio, self._config.sample_rate)
        segment = SpeechSegment(
            audio=audio,
            sample_rate=self._config.sample_rate,
            duration_ms=duration,
            session_id=self._session_id,
        )
        self._reset_to_idle()
        logger.info("VAD: Speech segment emitted (%.0fms)", duration)
        return SpeechEnded(segment)

    def _reset_to_idle(self) -> None:
        """Reset all state back to IDLE."""
        self._state = VADState.IDLE
        self._speech_buffer.clear()
        self._speech_duration_ms = 0
        self._silence_duration_ms = 0
        self._prefix_buffer.clear()
        self._vad.reset()

    @property
    def state(self) -> VADState:
        return self._state

    @property
    def is_speaking(self) -> bool:
        return self._state in (VADState.SPEECH_STARTED, VADState.SPEECH_ACTIVE)
