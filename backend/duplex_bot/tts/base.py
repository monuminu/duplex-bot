from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from duplex_bot.core.events import TTSAudioChunk


class TTSSession:
    """Reusable TTS session that pools the underlying connection.

    Default implementation delegates each call to the provider's
    ``synthesize_stream`` (no pooling).  Providers override this to
    keep a warm connection across multiple synthesis calls.
    """

    def __init__(self, tts: TTSBase):
        self._tts = tts

    async def synthesize_stream(
        self, text: str, voice: str | None = None
    ) -> AsyncIterator[TTSAudioChunk]:
        async for chunk in self._tts.synthesize_stream(text, voice):
            yield chunk

    async def synthesize_stream_incremental(
        self, text_chunks: AsyncIterator[str], voice: str | None = None
    ) -> AsyncIterator[TTSAudioChunk]:
        async for chunk in self._tts.synthesize_stream_incremental(text_chunks, voice):
            yield chunk

    async def close(self) -> None:
        pass


class TTSBase(ABC):
    """Abstract base class for Text-to-Speech providers."""

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream synthesized audio chunks for the given text.

        Args:
            text: Text to synthesize.
            voice: Voice ID/name override. Uses provider default if None.

        Yields:
            TTSAudioChunk with audio bytes, text span, and timing info.
        """
        yield  # pragma: no cover

    async def synthesize_stream_incremental(
        self,
        text_chunks: AsyncIterator[str],
        voice: str | None = None,
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream audio from incrementally arriving text chunks.

        Default: collects all text then synthesizes in one shot.
        Providers with native input streaming (ElevenLabs) override this.
        """
        full_text = ""
        async for chunk in text_chunks:
            full_text += chunk
        if full_text.strip():
            async for audio in self.synthesize_stream(full_text, voice):
                yield audio

    def create_session(self) -> TTSSession:
        """Create a reusable session for connection pooling across sentences."""
        return TTSSession(self)

    @abstractmethod
    def output_sample_rate(self) -> int:
        """Sample rate of the generated audio."""
