from __future__ import annotations

import asyncio
import logging
import queue as thread_queue
from collections.abc import AsyncIterator

import azure.cognitiveservices.speech as speechsdk

from duplex_bot.config import AzureSpeechConfig, AzureTTSConfig
from duplex_bot.core.audio import pcm_duration_ms
from duplex_bot.core.azure_token import AzureTokenProvider
from duplex_bot.core.events import TTSAudioChunk
from duplex_bot.tts.base import TTSBase, TTSSession

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 4096


class AzureSpeechTTS(TTSBase):
    """Azure Speech SDK TTS using text streaming via WebSocket v2 endpoint.

    Uses SpeechSynthesisRequest with TextStream input type and the
    synthesizing callback for true streaming audio output — chunks arrive
    via callback as they are generated, not after synthesis completes.
    """

    def __init__(
        self,
        speech_config: AzureSpeechConfig,
        tts_config: AzureTTSConfig,
        token_provider: AzureTokenProvider | None = None,
    ):
        self._speech_config = speech_config
        self._tts_config = tts_config
        self._sample_rate = self._parse_sample_rate(tts_config.output_format)
        self._token_provider = token_provider

    def _parse_sample_rate(self, output_format: str) -> int:
        if "16Khz" in output_format or "16khz" in output_format:
            return 16000
        if "24Khz" in output_format or "24khz" in output_format:
            return 24000
        if "8Khz" in output_format or "8khz" in output_format:
            return 8000
        return 16000

    def _get_entra_token(self) -> str:
        if self._token_provider is None:
            raise RuntimeError("No token provider configured for Entra auth")
        return self._token_provider.token

    def _get_speech_config(self) -> speechsdk.SpeechConfig:
        region = self._speech_config.region
        endpoint = f"wss://{region}.tts.speech.microsoft.com/cognitiveservices/websocket/v2"

        if self._speech_config.auth_mode == "key":
            config = speechsdk.SpeechConfig(
                endpoint=endpoint,
                subscription=self._speech_config.subscription_key,
            )
        else:
            aad_token = self._get_entra_token()
            resource_id = self._speech_config.resource_id
            config = speechsdk.SpeechConfig(endpoint=endpoint)
            config.authorization_token = f"aad#{resource_id}#{aad_token}"

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

    def create_session(self) -> TTSSession:
        return AzureTTSSession(self)

    async def synthesize_stream_incremental(
        self,
        text_chunks: AsyncIterator[str],
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream text chunks to Azure TTS as they arrive from the LLM.

        Uses the TextStream input type so audio starts flowing back before
        all text has been received — dramatically reducing TTFB compared
        to the base-class fallback that buffers everything first.
        """
        loop = asyncio.get_event_loop()
        audio_q: asyncio.Queue[TTSAudioChunk | None] = asyncio.Queue()
        text_q: thread_queue.Queue[str | None] = thread_queue.Queue()

        def _synth_thread() -> None:
            config = self._get_speech_config()
            if voice:
                config.speech_synthesis_voice_name = voice

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
                            text_span="",
                            cumulative_duration_ms=cumulative_ms,
                            sample_rate=self._sample_rate,
                        )
                        loop.call_soon_threadsafe(audio_q.put_nowait, chunk)

            synthesizer.synthesizing.connect(synthesizing_cb)

            tts_request = speechsdk.SpeechSynthesisRequest(
                input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream,
            )
            tts_task = synthesizer.speak_async(tts_request)

            while True:
                text = text_q.get()
                if text is None:
                    break
                tts_request.input_stream.write(text)

            tts_request.input_stream.close()
            result = tts_task.get()

            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                cancellation = getattr(result, "cancellation_details", None)
                logger.error(
                    "Azure TTS incremental failed: reason=%s, error_code=%s, details=%s",
                    result.reason,
                    getattr(cancellation, "error_code", "N/A") if cancellation else "N/A",
                    getattr(cancellation, "error_details", "N/A") if cancellation else "N/A",
                )

            loop.call_soon_threadsafe(audio_q.put_nowait, None)

        fut = loop.run_in_executor(None, _synth_thread)

        async def _feed_text() -> None:
            try:
                async for chunk in text_chunks:
                    if chunk:
                        text_q.put(chunk)
            finally:
                text_q.put(None)

        feed_task = asyncio.create_task(_feed_text())

        try:
            while True:
                chunk = await audio_q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            feed_task.cancel()
            await asyncio.gather(feed_task, return_exceptions=True)
            await fut

    def output_sample_rate(self) -> int:
        return self._sample_rate


class AzureTTSSession(TTSSession):
    """Keeps a single SpeechSynthesizer alive across multiple sentences.

    The first ``synthesize_stream`` call creates the synthesizer (which
    opens a WebSocket to Azure).  Subsequent calls reuse it, avoiding
    the ~1.5-2 s connection-setup TTFB on every sentence.
    """

    def __init__(self, tts: AzureSpeechTTS):
        self._tts = tts
        self._synthesizer: speechsdk.SpeechSynthesizer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_q: asyncio.Queue[TTSAudioChunk | None] | None = None
        self._cumulative_ms = 0.0
        self._current_text = ""

    def _ensure_synthesizer(self, voice: str | None = None) -> speechsdk.SpeechSynthesizer:
        if self._synthesizer is not None:
            return self._synthesizer
        config = self._tts._get_speech_config()
        if voice:
            config.speech_synthesis_voice_name = voice
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None,
        )
        self._synthesizer.synthesizing.connect(self._on_audio)
        logger.info("Azure TTS session: synthesizer created (pooled)")
        return self._synthesizer

    def _on_audio(self, evt: speechsdk.SpeechSynthesisEventArgs) -> None:
        if not evt.result.audio_data or not self._audio_q or not self._loop:
            return
        for i in range(0, len(evt.result.audio_data), READ_CHUNK_SIZE):
            chunk_data = evt.result.audio_data[i : i + READ_CHUNK_SIZE]
            dur = pcm_duration_ms(chunk_data, self._tts._sample_rate)
            self._cumulative_ms += dur
            self._loop.call_soon_threadsafe(
                self._audio_q.put_nowait,
                TTSAudioChunk(
                    audio=chunk_data,
                    text_span=self._current_text,
                    cumulative_duration_ms=self._cumulative_ms,
                    sample_rate=self._tts._sample_rate,
                ),
            )

    def _synth_in_thread(self, text: str, voice: str | None) -> None:
        synthesizer = self._ensure_synthesizer(voice)

        tts_request = speechsdk.SpeechSynthesisRequest(
            input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream,
        )
        tts_task = synthesizer.speak_async(tts_request)
        tts_request.input_stream.write(text)
        tts_request.input_stream.close()
        result = tts_task.get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            cancellation = getattr(result, "cancellation_details", None)
            logger.error(
                "Azure TTS session failed: reason=%s, error_code=%s, details=%s",
                result.reason,
                getattr(cancellation, "error_code", "N/A") if cancellation else "N/A",
                getattr(cancellation, "error_details", "N/A") if cancellation else "N/A",
            )

        self._loop.call_soon_threadsafe(self._audio_q.put_nowait, None)

    async def synthesize_stream(
        self, text: str, voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        if not text.strip():
            return

        self._loop = asyncio.get_event_loop()
        self._audio_q = asyncio.Queue()
        self._cumulative_ms = 0.0
        self._current_text = text

        fut = self._loop.run_in_executor(None, self._synth_in_thread, text, voice)

        while True:
            chunk = await self._audio_q.get()
            if chunk is None:
                break
            yield chunk

        await fut

    async def synthesize_stream_incremental(
        self, text_chunks: AsyncIterator[str], voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream audio from incremental text using the pooled synthesizer."""
        self._loop = asyncio.get_event_loop()
        self._audio_q = asyncio.Queue()
        self._cumulative_ms = 0.0
        self._current_text = ""

        text_q: thread_queue.Queue[str | None] = thread_queue.Queue()

        def _synth_in_thread() -> None:
            synthesizer = self._ensure_synthesizer(voice)

            tts_request = speechsdk.SpeechSynthesisRequest(
                input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream,
            )
            tts_task = synthesizer.speak_async(tts_request)

            while True:
                text = text_q.get()
                if text is None:
                    break
                tts_request.input_stream.write(text)

            tts_request.input_stream.close()
            result = tts_task.get()

            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                cancellation = getattr(result, "cancellation_details", None)
                logger.error(
                    "Azure TTS session incremental failed: reason=%s, error_code=%s, details=%s",
                    result.reason,
                    getattr(cancellation, "error_code", "N/A") if cancellation else "N/A",
                    getattr(cancellation, "error_details", "N/A") if cancellation else "N/A",
                )

            self._loop.call_soon_threadsafe(self._audio_q.put_nowait, None)

        fut = self._loop.run_in_executor(None, _synth_in_thread)

        async def _feed_text() -> None:
            try:
                async for chunk in text_chunks:
                    if chunk:
                        self._current_text += chunk
                        text_q.put(chunk)
            finally:
                text_q.put(None)

        feed_task = asyncio.create_task(_feed_text())

        try:
            while True:
                chunk = await self._audio_q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            feed_task.cancel()
            await asyncio.gather(feed_task, return_exceptions=True)
            await fut

    async def close(self) -> None:
        self._synthesizer = None
        logger.info("Azure TTS session: synthesizer released")
