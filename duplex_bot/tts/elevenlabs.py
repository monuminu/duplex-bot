from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

import aiohttp

from duplex_bot.config import ElevenLabsConfig
from duplex_bot.core.audio import pcm_duration_ms
from duplex_bot.core.events import TTSAudioChunk
from duplex_bot.tts.base import TTSBase

logger = logging.getLogger(__name__)

ELEVENLABS_WS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


class ElevenLabsTTS(TTSBase):
    """ElevenLabs streaming TTS via WebSocket.

    Uses the input-streaming WebSocket API for ultra-low TTFB.
    Text chunks can be sent incrementally as they arrive from the LLM,
    and audio chunks are received back in real-time.
    """

    def __init__(self, config: ElevenLabsConfig):
        self._config = config
        self._sample_rate = self._parse_sample_rate(config.output_format)

    def _parse_sample_rate(self, output_format: str) -> int:
        if "16000" in output_format:
            return 16000
        if "22050" in output_format:
            return 22050
        if "24000" in output_format:
            return 24000
        if "44100" in output_format:
            return 44100
        return 16000

    def _build_ws_url(self, voice_id: str, auto_mode: bool = False) -> str:
        url = ELEVENLABS_WS_URL.format(voice_id=voice_id)
        url += f"?model_id={self._config.model_id}"
        url += f"&output_format={self._config.output_format}"
        if auto_mode:
            url += "&auto_mode=true"
        return url

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Synthesize a complete text string via ElevenLabs WebSocket."""
        if not text.strip():
            return

        voice_id = voice or self._config.voice_id
        url = self._build_ws_url(voice_id)
        cumulative_ms = 0.0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    await ws.send_json({
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                        "xi_api_key": self._config.api_key,
                    })

                    await ws.send_json({
                        "text": text,
                        "try_trigger_generation": True,
                    })
                    await ws.send_json({"text": ""})

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("audio"):
                                audio_bytes = base64.b64decode(data["audio"])
                                chunk_duration = pcm_duration_ms(
                                    audio_bytes, self._sample_rate
                                )
                                cumulative_ms += chunk_duration
                                yield TTSAudioChunk(
                                    audio=audio_bytes,
                                    text_span=text,
                                    cumulative_duration_ms=cumulative_ms,
                                    sample_rate=self._sample_rate,
                                )
                            if data.get("isFinal"):
                                break
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            logger.error("ElevenLabs WS error: %s", msg.data)
                            break

        except Exception:
            logger.exception("ElevenLabs TTS streaming failed")

    async def synthesize_stream_incremental(
        self,
        text_chunks: AsyncIterator[str],
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream text tokens to ElevenLabs as LLM produces them.

        Opens one WebSocket session per response. Text sending and audio
        receiving run concurrently — audio starts flowing back as soon as
        ElevenLabs has enough context, not after all text is sent.
        """
        voice_id = voice or self._config.voice_id
        url = self._build_ws_url(voice_id, auto_mode=False)
        cumulative_ms = 0.0
        audio_q: asyncio.Queue[TTSAudioChunk | None] = asyncio.Queue()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    await ws.send_json({
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                        "xi_api_key": self._config.api_key,
                    })

                    async def _send():
                        try:
                            async for chunk in text_chunks:
                                if chunk:
                                    await ws.send_json({"text": chunk})
                            await ws.send_json({"text": ""})
                        except asyncio.CancelledError:
                            pass

                    async def _recv():
                        nonlocal cumulative_ms
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if data.get("audio"):
                                        audio_bytes = base64.b64decode(
                                            data["audio"]
                                        )
                                        dur = pcm_duration_ms(
                                            audio_bytes, self._sample_rate
                                        )
                                        cumulative_ms += dur
                                        await audio_q.put(
                                            TTSAudioChunk(
                                                audio=audio_bytes,
                                                text_span="",
                                                cumulative_duration_ms=cumulative_ms,
                                                sample_rate=self._sample_rate,
                                            )
                                        )
                                    if data.get("isFinal"):
                                        break
                                elif msg.type in (
                                    aiohttp.WSMsgType.ERROR,
                                    aiohttp.WSMsgType.CLOSED,
                                ):
                                    break
                        except asyncio.CancelledError:
                            pass
                        finally:
                            await audio_q.put(None)

                    send_task = asyncio.create_task(_send())
                    recv_task = asyncio.create_task(_recv())

                    try:
                        while True:
                            chunk = await audio_q.get()
                            if chunk is None:
                                break
                            yield chunk
                    finally:
                        send_task.cancel()
                        recv_task.cancel()
                        await asyncio.gather(
                            send_task, recv_task, return_exceptions=True
                        )

        except Exception:
            logger.exception("ElevenLabs incremental TTS failed")

    def output_sample_rate(self) -> int:
        return self._sample_rate
