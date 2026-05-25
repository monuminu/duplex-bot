from __future__ import annotations

import logging
import time
from typing import Any

from duplex_bot.config import LangfuseConfig

logger = logging.getLogger(__name__)


class SessionTracer:
    """Langfuse v4 observability for voice sessions.

    Each voice session = 1 Langfuse trace (root span).
    Each pipeline stage = a child span.
    Each LLM call = a generation observation.
    """

    def __init__(self, config: LangfuseConfig):
        self._config = config
        self._langfuse = None
        self._root_span = None
        self._root_cm = None
        self._propagate_cm = None
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
            from langfuse import propagate_attributes

            self._propagate_cm = propagate_attributes(
                session_id=session_id,
                trace_name="voice_session",
                metadata={"adapter": adapter_name},
            )
            self._propagate_cm.__enter__()

            self._root_cm = self._langfuse.start_as_current_observation(
                as_type="span",
                name="voice_session",
                input={"adapter": adapter_name, "session_id": session_id},
                metadata={"adapter": adapter_name, **(metadata or {})},
            )
            self._root_span = self._root_cm.__enter__()
        except Exception:
            logger.exception("Failed to create Langfuse trace")

    def end_session(
        self,
        turn_count: int = 0,
        barge_in_count: int = 0,
        **extra: Any,
    ) -> None:
        """Finalize the session trace with summary metrics."""
        session_duration = time.monotonic() * 1000 - self._session_start_ms

        if self._root_span:
            try:
                self._root_span.update(
                    output={
                        "session_duration_ms": session_duration,
                        "turn_count": turn_count,
                        "barge_in_count": barge_in_count,
                        **extra,
                    },
                )
            except Exception:
                logger.exception("Failed to update Langfuse trace")

        if self._root_cm:
            try:
                self._root_cm.__exit__(None, None, None)
            except Exception:
                logger.exception("Failed to close root span context")

        if self._propagate_cm:
            try:
                self._propagate_cm.__exit__(None, None, None)
            except Exception:
                logger.exception("Failed to close propagate_attributes context")

    def start_span(self, name: str, metadata: dict | None = None) -> str:
        """Start a named span within the session trace."""
        span_id = f"{name}_{time.monotonic_ns()}"
        self._span_start_times[span_id] = time.monotonic() * 1000

        if not self._root_span:
            return span_id

        try:
            span = self._root_span.start_observation(
                as_type="span",
                name=name,
                metadata=metadata or {},
            )
            self._spans[span_id] = span
        except Exception:
            logger.exception("Failed to create Langfuse span: %s", name)

        return span_id

    def end_span(self, name: str, metadata: dict | None = None) -> None:
        """End the most recent span with the given name."""
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
                span.update(
                    metadata={
                        "duration_ms": duration_ms,
                        **(metadata or {}),
                    },
                )
                span.end()
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
        if not self._root_span:
            return

        try:
            gen = self._root_span.start_observation(
                as_type="generation",
                name="llm_generation",
                model=model,
                input=input_messages,
                output=output,
                usage_details=usage,
            )
            gen.end()
        except Exception:
            logger.exception("Failed to record Langfuse generation")

    def record_event(self, name: str, metadata: dict | None = None) -> None:
        """Record a discrete event (barge-in, turn completion, etc.)."""
        if not self._root_span:
            return

        try:
            self._root_span.create_event(
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
