from __future__ import annotations

import logging
import time
from typing import Any

from duplex_bot.config import LangfuseConfig

logger = logging.getLogger(__name__)


class SessionTracer:
    """Langfuse-based observability for voice sessions.

    Each voice session = 1 Langfuse trace.
    Each pipeline stage = a span within that trace.
    Each LLM call = a generation within the trace.
    """

    def __init__(self, config: LangfuseConfig):
        self._config = config
        self._langfuse = None
        self._trace = None
        self._spans: dict[str, Any] = {}
        self._span_start_times: dict[str, float] = {}
        self._session_start_ms: float = 0

        if config.enabled and config.public_key:
            try:
                from langfuse import Langfuse
                self._langfuse = Langfuse(
                    public_key=config.public_key,
                    secret_key=config.secret_key,
                    host=config.host,
                )
            except ImportError:
                logger.warning("langfuse package not installed, observability disabled")
            except Exception:
                logger.exception("Failed to initialize Langfuse")

    def start_session(
        self,
        session_id: str,
        adapter_name: str,
        metadata: dict | None = None,
    ) -> None:
        """Create a Langfuse trace for this voice session."""
        self._session_start_ms = time.monotonic() * 1000
        if not self._langfuse:
            return

        try:
            self._trace = self._langfuse.trace(
                name="voice_session",
                session_id=session_id,
                metadata={
                    "adapter": adapter_name,
                    **(metadata or {}),
                },
            )
        except Exception:
            logger.exception("Failed to create Langfuse trace")

    def end_session(
        self,
        turn_count: int = 0,
        barge_in_count: int = 0,
        **extra: Any,
    ) -> None:
        """Finalize the session trace with summary metrics."""
        if not self._trace:
            return

        session_duration = time.monotonic() * 1000 - self._session_start_ms

        try:
            self._trace.update(
                metadata={
                    "session_duration_ms": session_duration,
                    "turn_count": turn_count,
                    "barge_in_count": barge_in_count,
                    **extra,
                },
            )
        except Exception:
            logger.exception("Failed to update Langfuse trace")

    def start_span(self, name: str, metadata: dict | None = None) -> str:
        """Start a named span within the session trace.

        Returns a span_id string for tracking.
        """
        span_id = f"{name}_{time.monotonic_ns()}"
        self._span_start_times[span_id] = time.monotonic() * 1000

        if not self._trace:
            return span_id

        try:
            span = self._trace.span(
                name=name,
                metadata=metadata or {},
            )
            self._spans[span_id] = span
        except Exception:
            logger.exception("Failed to create Langfuse span: %s", name)

        return span_id

    def end_span(self, name: str, metadata: dict | None = None) -> None:
        """End the most recent span with the given name.

        Also records the span duration.
        """
        # Find the most recent span with this name
        matching = [
            sid for sid in self._spans if sid.startswith(f"{name}_")
        ]
        if not matching:
            return

        span_id = matching[-1]
        start_ms = self._span_start_times.pop(span_id, 0)
        duration_ms = time.monotonic() * 1000 - start_ms if start_ms else 0

        span = self._spans.pop(span_id, None)
        if span:
            try:
                span.end(
                    metadata={
                        "duration_ms": duration_ms,
                        **(metadata or {}),
                    },
                )
            except Exception:
                logger.exception("Failed to end Langfuse span: %s", name)

    def record_generation(
        self,
        model: str,
        input_messages: list[dict],
        output: str,
        usage: dict | None = None,
    ) -> None:
        """Record an LLM generation event."""
        if not self._trace:
            return

        try:
            self._trace.generation(
                name="llm_generation",
                model=model,
                input=input_messages,
                output=output,
                usage=usage,
            )
        except Exception:
            logger.exception("Failed to record Langfuse generation")

    def record_event(self, name: str, metadata: dict | None = None) -> None:
        """Record a discrete event (barge-in, turn completion, etc.)."""
        if not self._trace:
            return

        try:
            self._trace.event(
                name=name,
                metadata=metadata or {},
            )
        except Exception:
            logger.exception("Failed to record Langfuse event: %s", name)

    def flush(self) -> None:
        """Flush pending events to Langfuse."""
        if self._langfuse:
            try:
                self._langfuse.flush()
            except Exception:
                logger.exception("Failed to flush Langfuse")
