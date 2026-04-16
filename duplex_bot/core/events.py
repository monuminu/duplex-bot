from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AudioChunk:
    """Raw audio chunk from the telephony adapter."""
    data: bytes
    sample_rate: int
    timestamp_ms: float = field(default_factory=lambda: time.monotonic() * 1000)
    session_id: str = ""


@dataclass
class SpeechSegment:
    """Complete speech segment after VAD detects end of speech."""
    audio: bytes
    sample_rate: int
    duration_ms: float
    session_id: str = ""
    # Timestamp when the speech ended (input buffer committed)
    committed_at_ms: float = field(default_factory=lambda: time.monotonic() * 1000)


@dataclass
class Transcript:
    """Result from STT transcription."""
    text: str
    confidence: float = 1.0
    language: str = "en-US"
    session_id: str = ""


@dataclass
class LLMResponseChunk:
    """A streaming chunk from the LLM."""
    text: str = ""
    is_final: bool = False
    tool_calls: list[ToolCallFragment] | None = None
    session_id: str = ""


@dataclass
class ToolCallFragment:
    """Accumulated tool call data from streaming LLM response."""
    id: str = ""
    name: str = ""
    arguments: str = ""  # JSON string, accumulated across chunks


@dataclass
class TTSAudioChunk:
    """Audio chunk from TTS synthesis."""
    audio: bytes
    text_span: str
    cumulative_duration_ms: float
    sample_rate: int = 16000
    session_id: str = ""


@dataclass
class InterruptSignal:
    """Signal emitted when user speech is detected during agent playback."""
    playback_position_ms: float = 0.0
    session_id: str = ""
    timestamp_ms: float = field(default_factory=lambda: time.monotonic() * 1000)


@dataclass
class FunctionCallRequest:
    """A function call to be executed asynchronously."""
    call_id: str
    name: str
    arguments: dict
    session_id: str = ""


@dataclass
class FunctionCallResult:
    """Result of an async function call execution."""
    call_id: str
    name: str
    result: str  # JSON-serialized result
    error: str | None = None
    session_id: str = ""


@dataclass
class SessionMetadata:
    """Metadata extracted from the initial adapter connection."""
    session_id: str = ""
    call_id: str = ""
    stream_sid: str = ""
    caller_number: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class ControlEvent:
    """Generic control event from the adapter."""
    event_type: str  # "dtmf", "hangup", etc.
    data: dict = field(default_factory=dict)
    session_id: str = ""
