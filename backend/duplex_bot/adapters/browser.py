from __future__ import annotations

import json
import logging

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from duplex_bot.core.events import AudioChunk, ControlEvent, SessionMetadata, TTSAudioChunk
from duplex_bot.adapters.base import TelephonyAdapter

logger = logging.getLogger(__name__)

# Browser uses 16kHz 16-bit PCM natively
BROWSER_SAMPLE_RATE = 16000


class BrowserAdapter(TelephonyAdapter):
    """Adapter for browser-based UI WebSocket connections.

    Protocol:
    - Audio: Binary WebSocket frames containing raw 16kHz 16-bit PCM
    - Control: Text WebSocket frames containing JSON messages
      - {"type": "start"} — session start
      - {"type": "stop"} — session end
      - {"type": "config", ...} — session configuration
    - Outbound audio: Binary frames with raw PCM
    - Outbound control: JSON text frames
      - {"type": "clear"} — stop playback
      - {"type": "transcript", "text": "..."} — show transcript
      - {"type": "agent_text", "text": "..."} — show agent response
    """

    async def on_connect(self, websocket: WebSocket) -> SessionMetadata:
        """Read optional start message from the browser client."""
        metadata = SessionMetadata()

        try:
            # Try to read a start message (with timeout)
            msg = await websocket.receive()
            if "text" in msg:
                data = json.loads(msg["text"])
                if data.get("type") == "start":
                    metadata.extra = data.get("config", {})
                    metadata.session_id = data.get("session_id", "")
                    logger.info("Browser session started: %s", metadata.extra)
        except Exception:
            logger.debug("No start message from browser client")

        return metadata

    async def receive(self, websocket: WebSocket) -> AudioChunk | ControlEvent | None:
        """Receive one message from the browser client."""
        msg = await websocket.receive()

        # Binary frame = audio data
        if "bytes" in msg and msg["bytes"]:
            return AudioChunk(
                data=msg["bytes"],
                sample_rate=BROWSER_SAMPLE_RATE,
            )

        # Text frame = control message
        if "text" in msg and msg["text"]:
            try:
                data = json.loads(msg["text"])
                event_type = data.get("type", "")

                if event_type == "stop":
                    return ControlEvent(event_type="stop")

                if event_type == "config":
                    return ControlEvent(event_type="config", data=data)

                return ControlEvent(event_type=event_type, data=data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from browser: %s", msg["text"][:100])
                return None

        return None

    async def send_audio(self, websocket: WebSocket, chunk: TTSAudioChunk) -> None:
        """Send audio as binary PCM frame to the browser."""
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_bytes(chunk.audio)

    async def send_clear(self, websocket: WebSocket) -> None:
        """Send clear signal to stop browser playback."""
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(json.dumps({"type": "clear"}))

    async def send_mark(self, websocket: WebSocket, mark_name: str) -> None:
        """Browser doesn't support marks — no-op."""
        pass

    async def send_text(self, websocket: WebSocket, event_type: str, text: str) -> None:
        """Send a text event to the browser (for UI display)."""
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(json.dumps({"type": event_type, "text": text}))

    def input_sample_rate(self) -> int:
        return BROWSER_SAMPLE_RATE

    def output_sample_rate(self) -> int:
        return BROWSER_SAMPLE_RATE

    @property
    def name(self) -> str:
        return "browser"
