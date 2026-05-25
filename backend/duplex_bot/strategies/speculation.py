from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher

from duplex_bot.core.conversation import ConversationHistory
from duplex_bot.llm.base import LLMBase

logger = logging.getLogger(__name__)

# Common short responses that users give
DEFAULT_SPECULATIVE_INPUTS = [
    "yes",
    "no",
    "okay",
    "tell me more",
    "go on",
    "what else",
    "that's all",
    "thank you",
]

# Minimum similarity ratio to consider a match
MATCH_THRESHOLD = 0.6


class SpeculativeGenerator:
    """Pre-generates likely responses during user silence.

    After the agent finishes speaking, this generator predicts likely
    short user responses and pre-generates LLM responses for them.
    If the user's actual input matches a prediction, the cached
    response is used immediately, saving the full LLM round-trip.
    """

    def __init__(
        self,
        llm: LLMBase,
        conversation: ConversationHistory,
        speculative_inputs: list[str] | None = None,
        max_concurrent: int = 3,
    ):
        self._llm = llm
        self._conversation = conversation
        self._inputs = speculative_inputs or DEFAULT_SPECULATIVE_INPUTS
        self._max_concurrent = max_concurrent

        # Cached predictions: {predicted_input: generated_response}
        self._cache: dict[str, str] = {}
        self._tasks: list[asyncio.Task] = []
        self._is_active = False

    async def start_speculation(self) -> None:
        """Begin generating speculative responses.

        Called after the agent finishes speaking, during user silence.
        """
        if self._is_active:
            return

        self._is_active = True
        self._cache.clear()

        # Select top-N most likely inputs
        inputs_to_try = self._inputs[: self._max_concurrent]

        for predicted_input in inputs_to_try:
            task = asyncio.create_task(
                self._generate_for(predicted_input),
                name=f"speculate_{predicted_input}",
            )
            self._tasks.append(task)

        logger.debug("Speculation started for %d predictions", len(inputs_to_try))

    async def _generate_for(self, predicted_input: str) -> None:
        """Generate a response for a predicted user input."""
        try:
            # Build messages with the predicted input appended
            messages = self._conversation.get_messages()
            messages.append({"role": "user", "content": predicted_input})

            full_response = ""
            async for chunk in self._llm.generate_stream(messages, temperature=0.3):
                full_response += chunk.text
                if chunk.is_final:
                    break

            if full_response:
                self._cache[predicted_input.lower()] = full_response
                logger.debug(
                    "Speculative response cached for '%s': '%s...'",
                    predicted_input,
                    full_response[:50],
                )

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Speculation failed for '%s'", predicted_input)

    def try_match(self, actual_transcript: str) -> str | None:
        """Check if the actual user input matches a speculative prediction.

        Args:
            actual_transcript: What the user actually said.

        Returns:
            Pre-generated response if matched, None otherwise.
        """
        if not self._cache:
            return None

        actual = actual_transcript.strip().lower()

        # Exact match
        if actual in self._cache:
            logger.info("Speculation hit (exact): '%s'", actual)
            return self._cache[actual]

        # Fuzzy match
        best_match = None
        best_ratio = 0.0

        for predicted, response in self._cache.items():
            ratio = SequenceMatcher(None, actual, predicted).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = (predicted, response)

        if best_match and best_ratio >= MATCH_THRESHOLD:
            logger.info(
                "Speculation hit (fuzzy %.2f): '%s' → '%s'",
                best_ratio,
                actual,
                best_match[0],
            )
            return best_match[1]

        logger.debug("No speculation match for '%s' (best ratio: %.2f)", actual, best_ratio)
        return None

    async def cancel(self) -> None:
        """Cancel all speculative generation tasks."""
        self._is_active = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._cache.clear()

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def cache_size(self) -> int:
        return len(self._cache)
