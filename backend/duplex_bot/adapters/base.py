from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import WebSocket

from duplex_bot.core.events import AudioChunk, ControlEvent, SessionMetadata, TTSAudioChunk


class TelephonyAdapter(ABC):
    """Abstract base class for telephony/UI WebSocket adapters.

    Each adapter normalizes a specific external system's WebSocket events
    into the internal event format and vice versa.

    To add a new provider: subclass this and implement all abstract methods.
    """

    @abstractmethod
    async def on_connect(self, websocket: WebSocket) -> SessionMetadata:
        """Handle initial connection handshake.

        Read any initial setup messages from the WebSocket and return
        session metadata (call_id, stream info, etc.).
        """

    @abstractmethod
    async def receive(self, websocket: WebSocket) -> AudioChunk | ControlEvent | None:
        """Read and deserialize one inbound WebSocket message.

        Returns:
            AudioChunk for audio data, ControlEvent for control messages,
            or None if the message should be ignored.
        """

    @abstractmethod
    async def send_audio(self, websocket: WebSocket, chunk: TTSAudioChunk) -> None:
        """Serialize and send outbound audio to the client."""

    @abstractmethod
    async def send_clear(self, websocket: WebSocket) -> None:
        """Send a 'clear/stop playback' message to the client."""

    @abstractmethod
    async def send_mark(self, websocket: WebSocket, mark_name: str) -> None:
        """Send a playback mark for tracking position. No-op if unsupported."""

    @abstractmethod
    def input_sample_rate(self) -> int:
        """Sample rate of audio arriving from this provider."""

    @abstractmethod
    def output_sample_rate(self) -> int:
        """Sample rate expected by this provider for outbound audio."""

    async def send_text(self, websocket: WebSocket, event_type: str, text: str) -> None:
        """Send a text event to the client (for UI display).

        Default is no-op. Override in adapters that support text display.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name identifier."""
