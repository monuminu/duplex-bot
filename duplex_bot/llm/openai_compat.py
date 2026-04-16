from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from duplex_bot.config import LLMConfig
from duplex_bot.core.events import LLMResponseChunk, ToolCallFragment
from duplex_bot.llm.base import LLMBase

logger = logging.getLogger(__name__)

EOT_SYSTEM_PROMPT = (
    "You are a turn-detection classifier for a voice conversation. "
    "Given the user's latest speech transcript and conversation context, "
    "determine whether the user has finished their turn (complete thought) "
    "or is likely to continue speaking. "
    "Respond with ONLY a JSON object: {\"done\": <float 0.0-1.0>} "
    "where 1.0 means definitely done speaking, 0.0 means definitely continuing."
)


class OpenAICompatibleLLM(LLMBase):
    """LLM client for any OpenAI-compatible chat completions API.

    Works with OpenAI, Azure OpenAI, Groq, Together, local vLLM, etc.
    """

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream chat completions from the LLM."""
        body: dict = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Accumulate tool calls across chunks
        tool_call_accumulators: dict[int, ToolCallFragment] = {}

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=body
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    logger.error("LLM API error %d: %s", response.status_code, error.decode())
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        # Emit final chunk with accumulated tool calls
                        final_tool_calls = list(tool_call_accumulators.values()) if tool_call_accumulators else None
                        yield LLMResponseChunk(
                            text="",
                            is_final=True,
                            tool_calls=final_tool_calls,
                        )
                        return

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Text content
                    text = delta.get("content") or ""

                    # Tool calls
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_accumulators:
                                tool_call_accumulators[idx] = ToolCallFragment(
                                    id=tc.get("id", ""),
                                    name=tc.get("function", {}).get("name", ""),
                                    arguments="",
                                )
                            acc = tool_call_accumulators[idx]
                            if tc.get("id"):
                                acc.id = tc["id"]
                            if tc.get("function", {}).get("name"):
                                acc.name = tc["function"]["name"]
                            acc.arguments += tc.get("function", {}).get("arguments", "")

                    if text:
                        yield LLMResponseChunk(text=text, is_final=False)

        except httpx.HTTPError:
            logger.exception("LLM streaming request failed")

    async def classify_end_of_turn(
        self,
        transcript: str,
        context: list[dict],
    ) -> float:
        """Use a fast LLM call to classify end-of-turn."""
        messages = [
            {"role": "system", "content": EOT_SYSTEM_PROMPT},
        ]
        # Include last few turns for context
        for msg in context[-4:]:
            messages.append(msg)
        messages.append({"role": "user", "content": f"Latest transcript: \"{transcript}\""})

        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._config.model,
                    "messages": messages,
                    "temperature": 0.0,
                    "max_tokens": 50,
                },
            )
            if response.status_code != 200:
                logger.warning("EOT classifier error %d", response.status_code)
                return 0.5

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            return float(parsed.get("done", 0.5))

        except Exception:
            logger.exception("EOT classification failed")
            return 0.5

    async def close(self) -> None:
        await self._client.aclose()
