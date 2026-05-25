from __future__ import annotations

from abc import ABC, abstractmethod


class VADBase(ABC):
    """Abstract base class for Voice Activity Detection."""

    @abstractmethod
    async def load(self) -> None:
        """Load model weights / initialize resources."""

    @abstractmethod
    async def process_chunk(self, chunk: bytes, sample_rate: int) -> float:
        """Process a single audio chunk and return speech probability.

        Args:
            chunk: Raw PCM audio bytes (16-bit mono).
            sample_rate: Sample rate of the audio.

        Returns:
            Speech probability in [0.0, 1.0].
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state between utterances."""
