from __future__ import annotations

import logging
import shlex
from contextlib import AsyncExitStack
from typing import Any

logger = logging.getLogger(__name__)


def _result_to_text(result: Any) -> str:
    """Flatten an MCP CallToolResult into a plain string for the LLM."""
    content = getattr(result, "content", None)
    if content is None:
        return str(result)

    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
            continue
        data = getattr(block, "data", None)
        if data is not None:
            parts.append(str(data))
        else:
            parts.append(str(block))
    return "\n".join(parts) if parts else ""


class MCPConnectionManager:
    """Connects to an agent's MCP servers and registers their tools.

    One instance lives for the duration of a single voice session. Connections
    are opened on ``connect_all`` and held open (via an AsyncExitStack) until
    ``close`` so tool calls during the conversation are low-latency. A failing
    server is logged and skipped — it never aborts the voice session.

    This sits entirely outside the voice core: it only feeds tool handlers into
    the per-session ``FunctionRegistry`` that ``VoiceSession`` already accepts.
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: list[Any] = []
        self.registered_tools: list[str] = []

    async def connect_all(self, mcp_configs: list[dict], registry: Any) -> None:
        for cfg in mcp_configs:
            if not cfg.get("is_enabled", True):
                continue
            try:
                await self._connect_one(cfg, registry)
            except Exception:  # noqa: BLE001 - isolate one bad server
                logger.exception(
                    "Failed to connect MCP server '%s'", cfg.get("server_name")
                )

    async def _connect_one(self, cfg: dict, registry: Any) -> None:
        from mcp import ClientSession

        server_name = cfg.get("server_name") or "mcp"
        session = await self._open_session(cfg, ClientSession)
        if session is None:
            return

        await session.initialize()
        self._sessions.append(session)

        allowlist = set(cfg.get("tool_allowlist") or [])
        tools_response = await session.list_tools()
        tools = getattr(tools_response, "tools", [])

        registered = 0
        for tool in tools:
            tool_name = getattr(tool, "name", None)
            if not tool_name:
                continue
            if allowlist and tool_name not in allowlist:
                continue

            qualified = self._qualified_name(server_name, tool_name, registry)
            schema = getattr(tool, "inputSchema", None) or {
                "type": "object",
                "properties": {},
            }
            description = (
                getattr(tool, "description", None)
                or f"{tool_name} (via {server_name} MCP server)"
            )
            handler = self._make_handler(session, tool_name)
            registry.register(
                name=qualified,
                handler=handler,
                description=description,
                parameters=schema,
            )
            self.registered_tools.append(qualified)
            registered += 1

        logger.info(
            "MCP server '%s' connected: %d tools registered", server_name, registered
        )

    async def _open_session(self, cfg: dict, client_session_cls: Any) -> Any | None:
        transport = (cfg.get("transport") or "").lower()
        server_url = cfg.get("server_url")
        command = cfg.get("command")
        headers = (cfg.get("config") or {}).get("headers") or {}

        # Infer transport when unspecified.
        if not transport:
            transport = "stdio" if command and not server_url else "streamable_http"

        if transport in {"streamable_http", "http", "streamablehttp"} and server_url:
            streams = await self._open_http(server_url, headers)
        elif transport in {"sse"} and server_url:
            streams = await self._open_sse(server_url, headers)
        elif transport in {"stdio"} and command:
            streams = await self._open_stdio(command, cfg)
        else:
            logger.warning(
                "MCP server '%s' has no usable transport/url/command; skipping",
                cfg.get("server_name"),
            )
            return None

        if streams is None:
            return None
        read_stream, write_stream = streams[0], streams[1]
        return await self._stack.enter_async_context(
            client_session_cls(read_stream, write_stream)
        )

    async def _open_http(self, url: str, headers: dict) -> Any:
        # Tolerate both the new (2-tuple) and deprecated (3-tuple) client names.
        try:
            from mcp.client.streamable_http import streamable_http_client

            return await self._stack.enter_async_context(
                streamable_http_client(url=url, headers=headers or None)
            )
        except ImportError:
            from mcp.client.streamable_http import streamablehttp_client

            return await self._stack.enter_async_context(
                streamablehttp_client(url=url, headers=headers or None)
            )

    async def _open_sse(self, url: str, headers: dict) -> Any:
        from mcp.client.sse import sse_client

        return await self._stack.enter_async_context(
            sse_client(url=url, headers=headers or None)
        )

    async def _open_stdio(self, command: str, cfg: dict) -> Any:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        parts = shlex.split(command)
        if not parts:
            return None
        params = StdioServerParameters(
            command=parts[0],
            args=parts[1:],
            env=(cfg.get("config") or {}).get("env") or None,
        )
        return await self._stack.enter_async_context(stdio_client(params))

    @staticmethod
    def _qualified_name(server_name: str, tool_name: str, registry: Any) -> str:
        """Namespace tool names per server to avoid collisions across servers."""
        base = tool_name
        if registry.get_handler(base) is None:
            return base
        safe_server = "".join(c if c.isalnum() else "_" for c in server_name)
        return f"{safe_server}__{tool_name}"

    @staticmethod
    def _make_handler(session: Any, tool_name: str):
        async def handler(**kwargs: Any) -> str:
            result = await session.call_tool(tool_name, kwargs)
            if getattr(result, "isError", False):
                return f"Tool error: {_result_to_text(result)}"
            return _result_to_text(result)

        return handler

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.debug("MCP cleanup raised during close", exc_info=True)
        self._sessions.clear()
