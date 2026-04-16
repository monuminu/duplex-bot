from __future__ import annotations

import asyncio
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

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Synthesize text via ElevenLabs WebSocket streaming API."""
        if not text.strip():
            return

        voice_id = voice or self._config.voice_id
        url = ELEVENLABS_WS_URL.format(voice_id=voice_id)
        url += f"?model_id={self._config.model_id}"
        url += f"&output_format={self._config.output_format}"
        url += f"&optimize_streaming_latency={self._config.optimize_streaming_latency}"

        cumulative_ms = 0.0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    # Send BOS (beginning of stream) message
                    bos_message = {
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                        "xi_api_key": self._config.api_key,
                    }
                    await ws.send_json(bos_message)

                    # Send the text
                    await ws.send_json({
                        "text": text,
                        "try_trigger_generation": True,
                    })

                    # Send EOS (end of stream) to flush
                    await ws.send_json({"text": ""})

                    # Receive audio chunks
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)

                            if data.get("audio"):
                                import base64
                                audio_bytes = base64.b64decode(data["audio"])
                                chunk_duration = pcm_duration_ms(audio_bytes, self._sample_rate)
                                cumulative_ms += chunk_duration

                                yield TTSAudioChunk(
                                    audio=audio_bytes,
                                    text_span=text,
                                    cumulative_duration_ms=cumulative_ms,
                                    sample_rate=self._sample_rate,
                                )

                            if data.get("isFinal"):
                                break

                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            logger.error("ElevenLabs WS error: %s", msg.data)
                            break

        except Exception:
            logger.exception("ElevenLabs TTS streaming failed")

    async def synthesize_stream_incremental(
        self,
        text_chunks: AsyncIterator[str],
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Send text incrementally as it arrives from the LLM.

        This is the ultra-low-latency path: text tokens are streamed
        to ElevenLabs as the LLM produces them, and audio is streamed back.
        """
        voice_id = voice or self._config.voice_id
        url = ELEVENLABS_WS_URL.format(voice_id=voice_id)
        url += f"?model_id={self._config.model_id}"
        url += f"&output_format={self._config.output_format}"
        url += f"&optimize_streaming_latency={self._config.optimize_streaming_latency}"

        cumulative_ms = 0.0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    # BOS
                    await ws.send_json({
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                        "xi_api_key": self._config.api_key,
                    })

                    # Start receiver task
                    audio_queue: asyncio.Queue[TTSAudioChunk | None] = asyncio.Queue()

                    async def receive_audio():
                        nonlocal cumulative_ms
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if data.get("audio"):
                                        import base64
                                        audio_bytes = base64.b64decode(data["audio"])
                                        chunk_duration = pcm_duration_ms(audio_bytes, self._sample_rate)
                                        cumulative_ms += chunk_duration
                                        await audio_queue.put(TTSAudioChunk(
                                            audio=audio_bytes,
                                            text_span="",
                                            cumulative_duration_ms=cumulative_ms,
                                            sample_rate=self._sample_rate,
                                        ))
                                    if data.get("isFinal"):
                                        break
                                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                    break
                        finally:
                            await audio_queue.put(None)

                    recv_task = asyncio.create_task(receive_audio())

                    # Send text chunks as they arrive
                    async for text_chunk in text_chunks:
                        if text_chunk:
                            await ws.send_json({
                                "text": text_chunk,
                                "try_trigger_generation": True,
                            })

                    # EOS
                    await ws.send_json({"text": ""})

                    # Yield received audio
                    while True:
                        chunk = await audio_queue.get()
                        if chunk is None:
                            break
                        yield chunk

                    await recv_task

        except Exception:
            logger.exception("ElevenLabs incremental TTS failed")

    def output_sample_rate(self) -> int:
        return self._sample_rate
