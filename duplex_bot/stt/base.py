from __future__ import annotations

from abc import ABC, abstractmethod

from duplex_bot.core.events import Transcript


class STTBase(ABC):
    """Abstract base class for Speech-to-Text providers."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        sample_rate: int,
        language: str = "en-US",
    ) -> Transcript:
        """Transcribe a complete audio segment.

        Args:
            audio: Raw PCM audio bytes (16-bit mono).
            sample_rate: Sample rate of the audio.
            language: BCP-47 language code.

        Returns:
            Transcript with text and confidence.
        """
