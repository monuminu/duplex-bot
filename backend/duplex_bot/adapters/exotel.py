from __future__ import annotations

import base64
import json
import logging

from fastapi import WebSocket

from duplex_bot.adapters.base import TelephonyAdapter
from duplex_bot.core.audio import mulaw_to_pcm, pcm_to_mulaw, resample_pcm
from duplex_bot.core.events import AudioChunk, ControlEvent, SessionMetadata, TTSAudioChunk

logger = logging.getLogger(__name__)

# Exotel/Twilio Media Streams use 8kHz mulaw
EXOTEL_SAMPLE_RATE = 8000
INTERNAL_SAMPLE_RATE = 16000


class ExotelAdapter(TelephonyAdapter):
    """Adapter for Exotel's WebSocket Media Streams (Twilio-style protocol).

    Event format:
    - Inbound: JSON with "event" field: "connected", "start", "media", "stop", "mark"
    - Audio: base64-encoded mulaw in media.payload at 8kHz
    - Outbound: JSON media events with base64-encoded mulaw audio
    """

    def __init__(self) -> None:
        self._stream_sid: str = ""

    async def on_connect(self, websocket: WebSocket) -> SessionMetadata:
        """Wait for 'connected' and 'start' events from Exotel."""
        metadata = SessionMetadata()

        # Read initial handshake messages
        for _ in range(10):  # Safety limit
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                logger.info("Exotel connected: %s", msg.get("protocol", ""))
                continue

            if event == "start":
                start_data = msg.get("start", {})
                self._stream_sid = start_data.get("streamSid", "")
                metadata.stream_sid = self._stream_sid
                metadata.call_id = start_data.get("callSid", "")
                metadata.extra = start_data.get("customParameters", {})
                logger.info(
                    "Exotel stream started: streamSid=%s, callSid=%s",
                    metadata.stream_sid,
                    metadata.call_id,
                )
                return metadata

        return metadata

    async def receive(self, websocket: WebSocket) -> AudioChunk | ControlEvent | None:
        """Deserialize one Exotel WebSocket message."""
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        event = msg.get("event", "")

        if event == "media":
            payload = msg.get("media", {}).get("payload", "")
            if not payload:
                return None

            # Decode base64 mulaw → PCM → resample to internal rate
            mulaw_bytes = base64.b64decode(payload)
            pcm_8k = mulaw_to_pcm(mulaw_bytes)
            pcm_16k = resample_pcm(pcm_8k, EXOTEL_SAMPLE_RATE, INTERNAL_SAMPLE_RATE)

            return AudioChunk(
                data=pcm_16k,
                sample_rate=INTERNAL_SAMPLE_RATE,
            )

        if event == "mark":
            mark_name = msg.get("mark", {}).get("name", "")
            return ControlEvent(event_type="mark", data={"name": mark_name})

        if event == "stop":
            logger.info("Exotel stream stopped")
            return ControlEvent(event_type="stop")

        if event == "dtmf":
            digit = msg.get("dtmf", {}).get("digit", "")
            return ControlEvent(event_type="dtmf", data={"digit": digit})

        return None

    async def send_audio(self, websocket: WebSocket, chunk: TTSAudioChunk) -> None:
        """Send audio back to Exotel as base64-encoded mulaw."""
        # Resample from internal rate to 8kHz and convert to mulaw
        pcm_8k = resample_pcm(chunk.audio, chunk.sample_rate, EXOTEL_SAMPLE_RATE)
        mulaw_bytes = pcm_to_mulaw(pcm_8k)
        payload = base64.b64encode(mulaw_bytes).decode("ascii")

        message = {
            "event": "media",
            "streamSid": self._stream_sid,
            "media": {
                "payload": payload,
            },
        }
        await websocket.send_text(json.dumps(message))

    async def send_clear(self, websocket: WebSocket) -> None:
        """Send clear event to stop playback on Exotel side."""
        message = {
            "event": "clear",
            "streamSid": self._stream_sid,
        }
        await websocket.send_text(json.dumps(message))

    async def send_mark(self, websocket: WebSocket, mark_name: str) -> None:
        """Send a mark event for playback tracking."""
        message = {
            "event": "mark",
            "streamSid": self._stream_sid,
            "mark": {
                "name": mark_name,
            },
        }
        await websocket.send_text(json.dumps(message))

    def input_sample_rate(self) -> int:
        return EXOTEL_SAMPLE_RATE

    def output_sample_rate(self) -> int:
        return EXOTEL_SAMPLE_RATE

    @property
    def name(self) -> str:
        return "exotel"
