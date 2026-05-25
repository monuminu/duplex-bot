from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# Common filler words and non-speech transcription artifacts
FILLER_PATTERNS: set[str] = {
    "um", "uh", "hmm", "hm", "mm", "mhm", "uh-huh", "uhuh",
    "ah", "oh", "eh", "er", "em", "umm", "uhm", "hmm",
    "yeah", "yep", "yup", "nah", "nope",
    "okay", "ok", "right", "sure",
}

# Noise artifact patterns from STT
NOISE_ARTIFACT_PATTERNS = [
    re.compile(r"^\[.*\]$"),          # [noise], [music], [laughter]
    re.compile(r"^\(.*\)$"),          # (inaudible), (background noise)
    re.compile(r"^<.*>$"),            # <silence>, <noise>
    re.compile(r"^\*.*\*$"),          # *cough*, *sigh*
    re.compile(r"^\.{2,}$"),          # ...
]


class NoiseFilter:
    """Filters out non-meaningful speech from STT transcripts.

    Rejects:
    - Pure filler words ("um", "uh", "hmm")
    - STT noise artifacts ("[noise]", "[music]")
    - Very short transcripts below minimum thresholds
    """

    def __init__(
        self,
        min_word_count: int = 1,
        min_char_length: int = 2,
        extra_fillers: set[str] | None = None,
    ):
        self._min_word_count = min_word_count
        self._min_char_length = min_char_length
        self._fillers = FILLER_PATTERNS | (extra_fillers or set())

    def is_meaningful(self, transcript: str) -> bool:
        """Return True if the transcript contains semantically meaningful content.

        Args:
            transcript: The STT transcript to evaluate.

        Returns:
            True if the transcript should be processed further.
        """
        cleaned = transcript.strip()
        if not cleaned:
            return False

        # Check minimum character length
        if len(cleaned) < self._min_char_length:
            return False

        # Check noise artifact patterns
        for pattern in NOISE_ARTIFACT_PATTERNS:
            if pattern.match(cleaned):
                logger.debug("Noise artifact filtered: '%s'", cleaned)
                return False

        # Normalize for filler check
        normalized = cleaned.lower().strip(".,!?;:")
        words = normalized.split()

        # Check minimum word count
        if len(words) < self._min_word_count:
            # Single-word check against fillers
            if normalized in self._fillers:
                logger.debug("Filler word filtered: '%s'", cleaned)
                return False

        # Check if ALL words are fillers
        if all(w.strip(".,!?;:") in self._fillers for w in words):
            logger.debug("All-filler transcript filtered: '%s'", cleaned)
            return False

        return True
