from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from duplex_bot.config import LLMConfig
from duplex_bot.core.azure_token import AzureTokenProvider
from duplex_bot.core.events import LLMResponseChunk, ToolCallFragment
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


class OpenAIRealtimeLLM(LLMBase):
    """LLM client using the OpenAI Realtime API in text-to-text mode.

    Opens a WebSocket connection per generate_stream call, sends
    conversation context as conversation items, and streams text
    deltas back. Supports tool/function calls.
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
        self._model = config.model

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMResponseChunk]:
        instructions = ""
        tool_calls: dict[str, ToolCallFragment] = {}

        try:
            async with self._client.realtime.connect(model=self._model) as conn:
                session_cfg: dict = {
                    "output_modalities": ["text"],
                    "temperature": temperature if temperature is not None else self._config.temperature,
                    "max_response_output_tokens": self._config.max_tokens,
                }

                if tools:
                    session_cfg["tools"] = self._convert_tool_schemas(tools)
                    session_cfg["tool_choice"] = "auto"

                for msg in messages:
                    if msg.get("role") == "system":
                        instructions = msg.get("content", "")

                if instructions:
                    session_cfg["instructions"] = instructions

                await conn.session.update(session=session_cfg)

                for msg in messages:
                    role = msg.get("role")
                    if role == "system":
                        continue
                    elif role == "user":
                        await conn.conversation.item.create(
                            item={
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": msg["content"]}],
                            }
                        )
                    elif role == "assistant":
                        if msg.get("content"):
                            await conn.conversation.item.create(
                                item={
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": msg["content"]}],
                                }
                            )
                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                await conn.conversation.item.create(
                                    item={
                                        "type": "function_call",
                                        "call_id": tc["id"],
                                        "name": tc["function"]["name"],
                                        "arguments": tc["function"]["arguments"],
                                    }
                                )
                    elif role == "tool":
                        await conn.conversation.item.create(
                            item={
                                "type": "function_call_output",
                                "call_id": msg["tool_call_id"],
                                "output": msg.get("content", ""),
                            }
                        )

                await conn.response.create()

                async for event in conn:
                    if event.type == "response.output_audio_transcript.delta":
                        yield LLMResponseChunk(text=event.delta, is_final=False)

                    elif event.type == "response.function_call_arguments.delta":
                        call_id = getattr(event, "call_id", "") or getattr(event, "item_id", "")
                        if call_id not in tool_calls:
                            tool_calls[call_id] = ToolCallFragment(
                                id=call_id,
                                name=getattr(event, "name", ""),
                            )
                        tool_calls[call_id].arguments += event.delta

                    elif event.type == "response.function_call_arguments.done":
                        call_id = getattr(event, "call_id", "") or getattr(event, "item_id", "")
                        if call_id in tool_calls:
                            tc = tool_calls[call_id]
                            name = getattr(event, "name", "") or tc.name
                            tc.name = name
                            tc.arguments = getattr(event, "arguments", tc.arguments)

                    elif event.type == "response.output_text.done":
                        final_tool_calls = list(tool_calls.values()) if tool_calls else None
                        yield LLMResponseChunk(
                            text="", is_final=True, tool_calls=final_tool_calls
                        )
                        break

        except (httpx.HTTPError, httpx.StreamError) as e:
            logger.warning("Realtime API streaming error: %s", e)
            yield LLMResponseChunk(text="", is_final=True)
        except Exception:
            logger.exception("Realtime API unexpected error")
            yield LLMResponseChunk(text="", is_final=True)

    @staticmethod
    def _convert_tool_schemas(tools: list[dict]) -> list[dict]:
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

    async def classify_end_of_turn(
        self,
        transcript: str,
        context: list[dict],
    ) -> float:
        """Use a one-shot Realtime API call to classify end-of-turn."""
        try:
            async with self._client.realtime.connect(model=self._model) as conn:
                await conn.session.update(
                    session={
                        "output_modalities": ["text"],
                        "temperature": 0.0,
                        "max_response_output_tokens": 50,
                        "instructions": EOT_SYSTEM_PROMPT,
                    }
                )

                for msg in context[-4:]:
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        content_type = "input_text" if msg["role"] == "user" else "text"
                        await conn.conversation.item.create(
                            item={
                                "type": "message",
                                "role": msg["role"],
                                "content": [{"type": content_type, "text": msg["content"]}],
                            }
                        )

                await conn.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f'Latest transcript: "{transcript}"'}],
                    }
                )

                await conn.response.create()

                output_text = ""
                async for event in conn:
                    if event.type == "response.output_text.delta":
                        output_text += event.delta
                    elif event.type == "response.done":
                        break

                try:
                    result = json.loads(output_text)
                    done_score = float(result.get("done", 0.5))
                    return max(0.0, min(1.0, done_score))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("EOT classification JSON parse error: %s", e)
                    return 0.5

        except Exception:
            logger.exception("EOT classification via Realtime API failed")
            return 0.5

    async def close(self) -> None:
        await self._client.close()