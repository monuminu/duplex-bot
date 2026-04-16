from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from duplex_bot.core.events import TTSAudioChunk


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

    @abstractmethod
    def output_sample_rate(self) -> int:
        """Sample rate of the generated audio."""
