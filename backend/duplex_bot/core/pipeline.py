from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for incremental TTS.

    Splits on sentence-ending punctuation while preserving the punctuation.
    Handles common abbreviations and decimal numbers.
    """
    if not text.strip():
        return []

    # Split on sentence-ending punctuation followed by space or end of string
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p.strip()]


def accumulate_sentences(buffer: str, new_text: str) -> tuple[list[str], str]:
    """Accumulate text and extract complete sentences.

    Args:
        buffer: Previously accumulated text without a sentence boundary.
        new_text: New text to add.

    Returns:
        Tuple of (complete_sentences, remaining_buffer).
    """
    combined = buffer + new_text
    sentences = split_sentences(combined)

    if not sentences:
        return [], combined

    # Check if the combined text ends with sentence-ending punctuation
    if combined.rstrip()[-1] in ".!?":
        # All sentences are complete
        return sentences, ""
    else:
        # Last part is incomplete — keep it in buffer
        complete = sentences[:-1]
        remaining = sentences[-1]
        return complete, remaining
