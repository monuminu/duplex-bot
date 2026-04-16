from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextAudioSegment:
    """Maps a text span to a time range in the TTS audio."""
    text: str
    start_ms: float
    end_ms: float


class TruncationTracker:
    """Tracks TTS playback position for auto-truncation on barge-in.

    Records which text maps to which audio duration, so that when the
    user interrupts, we can determine exactly which portion of the
    agent's response they actually heard.
    """

    def __init__(self) -> None:
        self._segments: list[TextAudioSegment] = []
        self._total_duration_ms: float = 0.0
        self._playback_start_time_ms: float = 0.0
        self._confirmed_playback_ms: float = 0.0  # From mark events
        self._barge_in_count: int = 0

    def record_segment(self, text: str, cumulative_duration_ms: float) -> None:
        """Record a TTS audio segment with its text and cumulative duration.

        Called each time a TTS audio chunk is sent to the client.

        Args:
            text: The text this chunk corresponds to.
            cumulative_duration_ms: Running total duration of audio sent.
        """
        if self._playback_start_time_ms == 0:
            self._playback_start_time_ms = time.monotonic() * 1000

        segment = TextAudioSegment(
            text=text,
            start_ms=self._total_duration_ms,
            end_ms=cumulative_duration_ms,
        )
        self._segments.append(segment)
        self._total_duration_ms = cumulative_duration_ms

    def on_mark_received(self, mark_name: str) -> None:
        """Update confirmed playback position from a mark event.

        Some adapters (Exotel/Twilio) send mark events confirming
        how far playback has progressed.
        """
        # Mark names encode the position, e.g., "mark_1500" for 1500ms
        try:
            if mark_name.startswith("mark_"):
                self._confirmed_playback_ms = float(mark_name.split("_")[1])
        except (ValueError, IndexError):
            pass

    @property
    def current_playback_ms(self) -> float:
        """Estimate current playback position.

        Uses confirmed mark position if available, otherwise estimates
        from wall-clock time since first audio was sent.
        """
        if self._confirmed_playback_ms > 0:
            return self._confirmed_playback_ms

        if self._playback_start_time_ms > 0:
            elapsed = time.monotonic() * 1000 - self._playback_start_time_ms
            # Don't exceed total audio sent
            return min(elapsed, self._total_duration_ms)

        return 0.0

    def get_heard_text(self, playback_position_ms: float) -> str:
        """Get the text the user heard up to the given playback position.

        Args:
            playback_position_ms: How far into playback when interrupted.

        Returns:
            The text that was heard, truncated at the appropriate point.
        """
        if not self._segments:
            return ""

        self._barge_in_count += 1
        heard_texts: list[str] = []
        seen_texts: set[str] = set()

        for seg in self._segments:
            if seg.start_ms >= playback_position_ms:
                break

            if seg.text not in seen_texts:
                if seg.end_ms <= playback_position_ms:
                    # Fully heard
                    heard_texts.append(seg.text)
                    seen_texts.add(seg.text)
                else:
                    # Partially heard — include the sentence anyway
                    # (we can't split mid-sentence meaningfully)
                    heard_texts.append(seg.text)
                    seen_texts.add(seg.text)

        result = " ".join(heard_texts)
        logger.debug(
            "Truncation: heard %.0fms of %.0fms → '%s'",
            playback_position_ms,
            self._total_duration_ms,
            result[:80],
        )
        return result

    def reset(self) -> None:
        """Reset for a new assistant turn."""
        self._segments.clear()
        self._total_duration_ms = 0.0
        self._playback_start_time_ms = 0.0
        self._confirmed_playback_ms = 0.0

    @property
    def barge_in_count(self) -> int:
        return self._barge_in_count
