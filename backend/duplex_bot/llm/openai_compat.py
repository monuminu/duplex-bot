from __future__ import annotations

import json
import logging
import time
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
    """LLM client for OpenAI, Azure OpenAI, or any compatible chat completions API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._is_azure = config.api_style == "azure"

        # Entra ID token caching (for Azure)
        self._credential = None
        self._cached_token: str = ""
        self._token_expires_at: float = 0

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._is_azure:
            if config.api_key:
                headers["api-key"] = config.api_key
            # else: token will be added per-request via _get_auth_headers()
        else:
            headers["Authorization"] = f"Bearer {config.api_key}"

        self._default_headers = headers
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def _get_entra_token(self) -> str:
        """Get a cached Entra ID token, refreshing if needed."""
        now = time.time()
        if self._cached_token and now < self._token_expires_at - 60:
            return self._cached_token

        if self._credential is None:
            from azure.identity import DefaultAzureCredential
            self._credential = DefaultAzureCredential(exclude_managed_identity_credential=True)

        token = self._credential.get_token("https://cognitiveservices.azure.com/.default")
        self._cached_token = token.token
        self._token_expires_at = token.expires_on
        logger.debug("Azure Entra LLM token refreshed")
        return self._cached_token

    def _get_auth_headers(self) -> dict[str, str]:
        """Get auth headers, using Entra token for Azure when no api_key."""
        if self._is_azure and not self._config.api_key:
            return {"Authorization": f"Bearer {self._get_entra_token()}"}
        return {}

    def _chat_path(self) -> str:
        """Return the chat completions endpoint path."""
        if self._is_azure:
            # Azure OpenAI: /openai/deployments/{model}/chat/completions?api-version=...
            return (
                f"/openai/deployments/{self._config.model}/chat/completions"
                f"?api-version=2024-10-21"
            )
        return "/chat/completions"

    async def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMResponseChunk]:
        """Stream chat completions from the LLM."""
        body: dict = {
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        # Azure OpenAI infers model from deployment name in the URL
        if not self._is_azure:
            body["model"] = self._config.model

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Accumulate tool calls across chunks
        tool_call_accumulators: dict[int, ToolCallFragment] = {}

        try:
            async with self._client.stream(
                "POST", self._chat_path(), json=body, headers=self._get_auth_headers()
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

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

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

        except (httpx.HTTPError, httpx.StreamError, Exception) as e:
            logger.warning("LLM streaming error: %s", e)
            # Emit final chunk so TTS gets the done marker
            yield LLMResponseChunk(text="", is_final=True)

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

        body: dict = {
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 50,
        }
        if not self._is_azure:
            body["model"] = self._config.model

        try:
            response = await self._client.post(self._chat_path(), json=body, headers=self._get_auth_headers())
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
