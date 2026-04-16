from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import azure.cognitiveservices.speech as speechsdk

from duplex_bot.config import AzureSpeechConfig, AzureTTSConfig
from duplex_bot.core.audio import pcm_duration_ms
from duplex_bot.core.events import TTSAudioChunk
from duplex_bot.tts.base import TTSBase

logger = logging.getLogger(__name__)

# Chunk size for reading from the pull stream (4KB = ~125ms at 16kHz 16-bit)
READ_CHUNK_SIZE = 4096


class AzureSpeechTTS(TTSBase):
    """Azure Speech SDK TTS with streaming output.

    Uses PullAudioOutputStream + thread executor to bridge the synchronous
    SDK into asyncio.
    """

    def __init__(self, speech_config: AzureSpeechConfig, tts_config: AzureTTSConfig):
        self._speech_config = speech_config
        self._tts_config = tts_config
        self._sample_rate = self._parse_sample_rate(tts_config.output_format)

    def _parse_sample_rate(self, output_format: str) -> int:
        """Extract sample rate from Azure output format string."""
        if "16Khz" in output_format or "16khz" in output_format:
            return 16000
        if "24Khz" in output_format or "24khz" in output_format:
            return 24000
        if "8Khz" in output_format or "8khz" in output_format:
            return 8000
        return 16000

    def _get_speech_config(self) -> speechsdk.SpeechConfig:
        config = speechsdk.SpeechConfig(
            subscription=self._speech_config.subscription_key,
            region=self._speech_config.region,
        )
        config.speech_synthesis_voice_name = self._tts_config.voice_name
        # Set output format
        format_map = {
            "Raw16Khz16BitMonoPcm": speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
            "Raw24Khz16BitMonoPcm": speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
            "Raw8Khz16BitMonoPcm": speechsdk.SpeechSynthesisOutputFormat.Raw8Khz16BitMonoPcm,
        }
        fmt = format_map.get(
            self._tts_config.output_format,
            speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
        )
        config.set_speech_synthesis_output_format(fmt)
        return config

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Synthesize text and stream audio chunks."""
        if not text.strip():
            return

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[TTSAudioChunk | None] = asyncio.Queue()

        # Run synthesis in thread to avoid blocking the event loop
        await loop.run_in_executor(
            None,
            self._synthesize_to_queue,
            text,
            voice,
            queue,
            loop,
        )

        # Yield chunks from the queue
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    def _synthesize_to_queue(
        self,
        text: str,
        voice: str | None,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Synchronous synthesis that pushes chunks into an asyncio queue."""
        config = self._get_speech_config()
        if voice:
            config.speech_synthesis_voice_name = voice

        # Use pull stream for reading audio data
        pull_stream = speechsdk.audio.PullAudioOutputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=pull_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config,
            audio_config=audio_config,
        )

        result = synthesizer.speak_text(text)

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            cumulative_ms = 0.0

            # Split into chunks and push to queue
            for i in range(0, len(audio_data), READ_CHUNK_SIZE):
                chunk_data = audio_data[i : i + READ_CHUNK_SIZE]
                chunk_duration = pcm_duration_ms(chunk_data, self._sample_rate)
                cumulative_ms += chunk_duration

                chunk = TTSAudioChunk(
                    audio=chunk_data,
                    text_span=text,
                    cumulative_duration_ms=cumulative_ms,
                    sample_rate=self._sample_rate,
                )
                loop.call_soon_threadsafe(queue.put_nowait, chunk)

            # Signal completion
            loop.call_soon_threadsafe(queue.put_nowait, None)
        else:
            logger.error(
                "Azure TTS failed: reason=%s, details=%s",
                result.reason,
                result.cancellation_details if hasattr(result, "cancellation_details") else "N/A",
            )
            loop.call_soon_threadsafe(queue.put_nowait, None)

    def output_sample_rate(self) -> int:
        return self._sample_rate
