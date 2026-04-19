from __future__ import annotations

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


class ConversationHistory:
    """Manages the chat message list with auto-truncation support.

    Tracks assistant messages and supports truncating the last assistant
    response to only the portion the user actually heard (for barge-in).
    """

    def __init__(self, system_prompt: str, max_turns: int = 50):
        self._system_message = {"role": "system", "content": system_prompt}
        self._messages: list[dict] = []
        self._max_turns = max_turns

    def add_user_message(self, text: str) -> None:
        """Add a user message to the conversation."""
        self._messages.append({"role": "user", "content": text})
        self._trim_if_needed()

    def add_assistant_message(self, text: str) -> None:
        """Add a complete assistant message to the conversation."""
        self._messages.append({"role": "assistant", "content": text})
        self._trim_if_needed()

    def truncate_last_assistant(self, heard_text: str) -> None:
        """Replace the last assistant message with only the heard portion.

        Called on barge-in: the user only heard part of the response,
        so the conversation history should reflect only what they heard.
        """
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i]["role"] == "assistant":
                original = self._messages[i]["content"]
                if heard_text and heard_text != original:
                    self._messages[i]["content"] = heard_text
                    logger.debug(
                        "Truncated assistant message: '%s...' → '%s...'",
                        original[:50],
                        heard_text[:50],
                    )
                return
        logger.warning("No assistant message found to truncate")

    def get_last_assistant_content(self) -> str | None:
        """Return the content of the last assistant message, or None."""
        for msg in reversed(self._messages):
            if msg["role"] == "assistant" and isinstance(msg.get("content"), str):
                return msg["content"]
        return None

    def restore_last_assistant(self, full_text: str) -> None:
        """Restore the last assistant message to its full text.

        Inverse of truncate_last_assistant — used when a barge-in turns
        out to be a false positive and we need to undo the truncation.
        """
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i]["role"] == "assistant":
                self._messages[i]["content"] = full_text
                logger.debug("Restored assistant message to full text: '%s...'", full_text[:50])
                return

    def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        """Record that the assistant made a tool call."""
        # Append to the last assistant message or create a new one
        self._messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }],
        })

    def add_function_result(self, call_id: str, name: str, result: str) -> None:
        """Add the result of a function call."""
        self._messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": result,
        })

    def get_messages(self) -> list[dict]:
        """Get the full message list including system prompt."""
        return [self._system_message] + deepcopy(self._messages)

    def get_context(self, last_n: int = 6) -> list[dict]:
        """Get recent messages for context (e.g., for turn detection)."""
        return deepcopy(self._messages[-last_n:])

    def _trim_if_needed(self) -> None:
        """Remove oldest turns if we exceed max_turns (keep pairs)."""
        # Count user+assistant pairs
        while len(self._messages) > self._max_turns * 2:
            # Remove the oldest user + assistant pair
            if len(self._messages) >= 2:
                self._messages.pop(0)
                self._messages.pop(0)

    @property
    def turn_count(self) -> int:
        """Number of completed conversation turns (user→assistant pairs)."""
        return sum(1 for m in self._messages if m["role"] == "user")

    def clear(self) -> None:
        self._messages.clear()
