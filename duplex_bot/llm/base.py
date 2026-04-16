from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from duplex_bot.core.events import LLMResponseChunk


class LLMBase(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream LLM response chunks.

        Args:
            messages: Chat messages in OpenAI format.
            tools: Tool definitions in OpenAI format, if any.
            temperature: Sampling temperature.

        Yields:
            LLMResponseChunk with delta text and/or tool call fragments.
        """
        yield  # pragma: no cover

    @abstractmethod
    async def classify_end_of_turn(
        self,
        transcript: str,
        context: list[dict],
    ) -> float:
        """Classify whether the user has finished their turn.

        Args:
            transcript: The latest user transcript.
            context: Recent conversation history for context.

        Returns:
            Probability [0.0, 1.0] that the user is done speaking.
        """
