from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from duplex_bot.config import LLMConfig
from duplex_bot.core.azure_token import AzureTokenProvider
from duplex_bot.core.events import LLMResponseChunk
from duplex_bot.llm.base import LLMBase
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

EOT_SYSTEM_PROMPT = (
    "You are a turn-detection classifier for a voice conversation. "
    "Given the user's latest speech transcript and conversation context, "
    "determine whether the user has finished their turn (complete thought) "
    "or is likely to continue speaking. "
    'Respond with ONLY a JSON object: {"done": <float 0.0-1.0>} '
    "where 1.0 means definitely done speaking, 0.0 means definitely continuing."
)


class OpenAIResponsesLLM(LLMBase):
    """LLM client using the OpenAI Responses API (POST /v1/responses).

    Yields every text delta immediately — no sentence buffering.
    Tool calls are accumulated and emitted on the final chunk.
    """

    def __init__(self, config: LLMConfig, token_provider: AzureTokenProvider | None = None):
        self._config = config
        if token_provider is not None:
            api_key = token_provider
        elif config.api_key:
            api_key = config.api_key
        else:
            raise ValueError("LLM requires either a shared AzureTokenProvider or an api_key in config")
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=api_key,
        )

    @staticmethod
    def _messages_to_input(messages: list[dict]) -> tuple[str, list[dict]]:
        """Convert chat-completions messages to Responses API input format.

        Returns (instructions, input_list) where instructions is the
        extracted system prompt.
        """
        instructions = ""
        input_list: list[dict] = []

        for msg in messages:
            role = msg.get("role")

            if role == "system":
                instructions = msg.get("content", "")

            elif role == "user":
                input_list.append({"role": "user", "content": msg["content"]})

            elif role == "assistant":
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        input_list.append({
                            "type": "function_call",
                            "call_id": tc["id"],
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        })
                elif msg.get("content"):
                    input_list.append({
                        "role": "assistant",
                        "content": msg["content"],
                    })

            elif role == "tool":
                input_list.append({
                    "type": "function_call_output",
                    "call_id": msg["tool_call_id"],
                    "output": msg.get("content", ""),
                })

        return instructions, input_list

    @staticmethod
    def _convert_tool_schemas(tools: list[dict]) -> list[dict]:
        """Convert chat-completions tool schemas to Responses API format.

        Chat Completions: {"type":"function","function":{"name":...}}
        Responses API:    {"type":"function","name":...}
        """
        converted = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                fn = tool["function"]
                converted.append({
                    "type": "function",
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                })
            else:
                converted.append(tool)
        return converted

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream response from the Responses API.

        Each text delta is yielded immediately as an LLMResponseChunk.
        Tool calls are accumulated and attached to the final chunk.
        """
        instructions, input_list = self._messages_to_input(messages)

        try:
            stream = await self._client.responses.create(
                model=self._config.model,
                input=input_list,
                stream=True,
                instructions=instructions,
                tools=self._convert_tool_schemas(tools or []),
                temperature=temperature or 0.0,
                max_output_tokens=100,
            )
            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield LLMResponseChunk(text=event.delta, is_final=False)
                elif event.type == "response.output_text.done":
                    yield LLMResponseChunk(text="", is_final=True)

        except (httpx.HTTPError, httpx.StreamError) as e:
            logger.warning("Responses API streaming error: %s", e)
            yield LLMResponseChunk(text="", is_final=True)

    async def classify_end_of_turn(
        self,
        transcript: str,
        context: list[dict],
    ) -> float:
        """Use a non-streaming Responses API call to classify end-of-turn."""
        input_list: list[dict] = []
        for msg in context[-4:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                input_list.append(
                    {"role": msg["role"], "content": msg["content"]}
                )
        input_list.append({
            "role": "user",
            "content": f'Latest transcript: "{transcript}"',
        })

        body: dict = {
            "model": self._config.model,
            "instructions": EOT_SYSTEM_PROMPT,
            "input": input_list,
            "temperature": 0.0,
            "max_output_tokens": 50,
        }

        try:
            response = await self._client.responses.create(**body)
            output = response.output_text
            try:
                result = json.loads(output)
                done_score = float(result.get("done", 0.5))
                return max(0.0, min(1.0, done_score))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("EOT classification JSON parse error: %s", e)
                return 0.5

        except Exception:
            logger.exception("EOT classification failed")
            return 0.5

    async def close(self) -> None:
        await self._client.close()
