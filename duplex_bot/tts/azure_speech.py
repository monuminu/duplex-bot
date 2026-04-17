from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

import azure.cognitiveservices.speech as speechsdk

from duplex_bot.config import AzureSpeechConfig, AzureTTSConfig
from duplex_bot.core.audio import pcm_duration_ms
from duplex_bot.core.events import TTSAudioChunk
from duplex_bot.tts.base import TTSBase

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 4096


class AzureSpeechTTS(TTSBase):
    """Azure Speech SDK TTS using text streaming via WebSocket v2 endpoint.

    Uses SpeechSynthesisRequest with TextStream input type and the
    synthesizing callback for true streaming audio output — chunks arrive
    via callback as they are generated, not after synthesis completes.
    """

    def __init__(self, speech_config: AzureSpeechConfig, tts_config: AzureTTSConfig):
        self._speech_config = speech_config
        self._tts_config = tts_config
        self._sample_rate = self._parse_sample_rate(tts_config.output_format)

        self._credential = None
        self._cached_token: str = ""
        self._token_expires_at: float = 0

    def _parse_sample_rate(self, output_format: str) -> int:
        if "16Khz" in output_format or "16khz" in output_format:
            return 16000
        if "24Khz" in output_format or "24khz" in output_format:
            return 24000
        if "8Khz" in output_format or "8khz" in output_format:
            return 8000
        return 16000

    def _get_entra_token(self) -> str:
        now = time.time()
        if self._cached_token and now < self._token_expires_at - 60:
            return self._cached_token

        if self._credential is None:
            from azure.identity import DefaultAzureCredential
            self._credential = DefaultAzureCredential()

        token = self._credential.get_token("https://cognitiveservices.azure.com/.default")
        self._cached_token = token.token
        self._token_expires_at = token.expires_on
        logger.debug("Azure Entra TTS token refreshed")
        return self._cached_token

    def _get_speech_config(self) -> speechsdk.SpeechConfig:
        region = self._speech_config.region
        endpoint = f"wss://{region}.tts.speech.microsoft.com/cognitiveservices/websocket/v2"

        if self._speech_config.auth_mode == "key":
            config = speechsdk.SpeechConfig(
                endpoint=endpoint,
                subscription=self._speech_config.subscription_key,
            )
        else:
            token = self._get_entra_token()
            config = speechsdk.SpeechConfig(
                endpoint=endpoint,
                auth_token=token,
            )

        config.speech_synthesis_voice_name = self._tts_config.voice_name

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

        # Prevent SDK from cancelling when LLM text streaming is slow
        config.set_property(
            speechsdk.PropertyId.SpeechSynthesis_FrameTimeoutInterval,
            "100000000",
        )
        config.set_property(
            speechsdk.PropertyId.SpeechSynthesis_RtfTimeoutThreshold,
            "10",
        )

        return config

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        if not text.strip():
            return

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[TTSAudioChunk | None] = asyncio.Queue()

        # Start synthesis in a background thread. Do NOT await yet — we need
        # to read audio chunks from the queue concurrently as the synthesizing
        # callback fires from the SDK's internal thread.
        fut = loop.run_in_executor(
            None,
            self._synthesize_to_queue,
            text,
            voice,
            queue,
            loop,
        )

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

        await fut

    def _synthesize_to_queue(
        self,
        text: str,
        voice: str | None,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        config = self._get_speech_config()
        if voice:
            config.speech_synthesis_voice_name = voice

        # audio_config=None suppresses speaker output on the server
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config,
            audio_config=None,
        )

        cumulative_ms = 0.0

        def synthesizing_cb(evt: speechsdk.SpeechSynthesisEventArgs) -> None:
            nonlocal cumulative_ms
            if evt.result.audio_data:
                audio_data = evt.result.audio_data
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

        synthesizer.synthesizing.connect(synthesizing_cb)

        logger.info(
            "Azure TTS: synthesizing '%s' (voice=%s)",
            text[:60],
            config.speech_synthesis_voice_name,
        )

        # TextStream request: enables the text streaming protocol over WS v2
        tts_request = speechsdk.SpeechSynthesisRequest(
            input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream,
        )
        tts_task = synthesizer.speak_async(tts_request)

        tts_request.input_stream.write(text)
        tts_request.input_stream.close()

        result = tts_task.get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.info("Azure TTS: synthesis complete")
        else:
            cancellation = getattr(result, "cancellation_details", None)
            logger.error(
                "Azure TTS failed: reason=%s, error_code=%s, details=%s",
                result.reason,
                getattr(cancellation, "error_code", "N/A") if cancellation else "N/A",
                getattr(cancellation, "error_details", "N/A") if cancellation else "N/A",
            )

        loop.call_soon_threadsafe(queue.put_nowait, None)

    def output_sample_rate(self) -> int:
        return self._sample_rate
