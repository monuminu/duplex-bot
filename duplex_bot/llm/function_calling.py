from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from duplex_bot.core.events import FunctionCallRequest, FunctionCallResult

logger = logging.getLogger(__name__)

# Type for registered function handlers
FunctionHandler = Callable[..., Coroutine[Any, Any, Any]]


class FunctionRegistry:
    """Registry of callable functions available to the LLM."""

    def __init__(self) -> None:
        self._functions: dict[str, FunctionHandler] = {}
        self._schemas: list[dict] = []

    def register(
        self,
        name: str,
        handler: FunctionHandler,
        description: str,
        parameters: dict,
    ) -> None:
        """Register a function that the LLM can call.

        Args:
            name: Function name (must match what the LLM will call).
            handler: Async callable that implements the function.
            description: Description for the LLM.
            parameters: JSON Schema for the function parameters.
        """
        self._functions[name] = handler
        self._schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
        logger.info("Registered function: %s", name)

    def get_handler(self, name: str) -> FunctionHandler | None:
        return self._functions.get(name)

    @property
    def tool_schemas(self) -> list[dict]:
        """Tool definitions in OpenAI format for the LLM."""
        return self._schemas

    @property
    def has_tools(self) -> bool:
        return len(self._functions) > 0


class FunctionExecutor:
    """Executes function calls asynchronously.

    Functions are never cancelled on barge-in — they run to completion
    and results are injected back into the conversation.
    """

    def __init__(self, registry: FunctionRegistry):
        self._registry = registry
        self._in_flight: dict[str, asyncio.Task] = {}

    async def execute(self, request: FunctionCallRequest) -> FunctionCallResult:
        """Execute a function call and return the result.

        Args:
            request: The function call to execute.

        Returns:
            FunctionCallResult with the serialized result or error.
        """
        handler = self._registry.get_handler(request.name)
        if handler is None:
            logger.error("Unknown function: %s", request.name)
            return FunctionCallResult(
                call_id=request.call_id,
                name=request.name,
                result="",
                error=f"Unknown function: {request.name}",
                session_id=request.session_id,
            )

        try:
            result = await handler(**request.arguments)
            result_str = json.dumps(result) if not isinstance(result, str) else result
            logger.info("Function %s completed successfully", request.name)
            return FunctionCallResult(
                call_id=request.call_id,
                name=request.name,
                result=result_str,
                session_id=request.session_id,
            )
        except Exception as e:
            logger.exception("Function %s failed", request.name)
            return FunctionCallResult(
                call_id=request.call_id,
                name=request.name,
                result="",
                error=str(e),
                session_id=request.session_id,
            )

    def execute_async(self, request: FunctionCallRequest) -> asyncio.Task[FunctionCallResult]:
        """Fire-and-forget execution. Returns the task for tracking.

        The task is NOT cancelled on barge-in.
        """
        task = asyncio.create_task(self.execute(request))
        self._in_flight[request.call_id] = task
        task.add_done_callback(lambda t: self._in_flight.pop(request.call_id, None))
        return task

    @property
    def pending_count(self) -> int:
        return len(self._in_flight)

    async def wait_all(self) -> list[FunctionCallResult]:
        """Wait for all in-flight function calls to complete."""
        if not self._in_flight:
            return []
        tasks = list(self._in_flight.values())
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, FunctionCallResult)]
