from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol, runtime_checkable

from duplex_bot.config import EndOfTurnConfig
from duplex_bot.llm.base import LLMBase

logger = logging.getLogger(__name__)


@runtime_checkable
class SemanticClassifier(Protocol):
    async def classify(self, transcript: str, context: list[dict]) -> float: ...


class LLMSemanticClassifier:
    def __init__(self, llm: LLMBase):
        self._llm = llm

    async def classify(self, transcript: str, context: list[dict]) -> float:
        return await self._llm.classify_end_of_turn(transcript, context)


class TurnDetector:
    """Detects end-of-turn using a two-tier approach:

    1. Hard silence threshold — if silence exceeds `silence_threshold_ms`,
       the turn is considered complete regardless of semantic analysis.
    2. Semantic classifier — after `semantic_check_after_ms` of silence,
       ask a classifier whether the user is done speaking.
    """

    def __init__(self, config: EndOfTurnConfig, classifier: SemanticClassifier):
        self._classifier = classifier
        self._config = config
        self._accumulated_text: str = ""
        self._last_transcript_time: float = 0

    def add_transcript(self, text: str) -> None:
        """Accumulate a new transcript fragment."""
        if self._accumulated_text:
            self._accumulated_text += " " + text
        else:
            self._accumulated_text = text
        self._last_transcript_time = time.monotonic() * 1000

    async def check_end_of_turn(
        self,
        silence_ms: float,
        context: list[dict],
    ) -> bool:
        """Check if the user has finished their turn.

        Args:
            silence_ms: Milliseconds of silence since last speech.
            context: Recent conversation context.

        Returns:
            True if the user is done speaking.
        """
        if not self._accumulated_text.strip():
            return False

        # Tier 1: Hard silence threshold
        if silence_ms >= self._config.silence_threshold_ms:
            logger.info("Turn complete: hard silence threshold (%.0fms)", silence_ms)
            return True

        # Tier 2: Semantic check after shorter silence
        if silence_ms >= self._config.semantic_check_after_ms:
            try:
                confidence = await self._classifier.classify(
                    self._accumulated_text, context
                )
                is_done = confidence >= self._config.semantic_confidence_threshold
                logger.info(
                    "Semantic EOT: confidence=%.3f, done=%s, text='%s'",
                    confidence,
                    is_done,
                    self._accumulated_text[:50],
                )
                return is_done
            except Exception:
                logger.exception("Semantic EOT check failed, falling back to silence")
                return False

        return False

    def get_accumulated_text(self) -> str:
        """Get the full accumulated text for this turn."""
        return self._accumulated_text.strip()

    def reset(self) -> None:
        """Reset for a new turn."""
        self._accumulated_text = ""
        self._last_transcript_time = 0
