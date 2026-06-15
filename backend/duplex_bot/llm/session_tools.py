from __future__ import annotations

import logging

from duplex_bot.config import AppConfig
from duplex_bot.db.models import VoiceAgent
from duplex_bot.db.session import get_session_factory
from duplex_bot.llm.function_calling import FunctionRegistry
from duplex_bot.llm.mcp_client import MCPConnectionManager
from duplex_bot.services import knowledge as knowledge_service

logger = logging.getLogger(__name__)


def _knowledge_tool_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question or topic to look up in the knowledge base.",
            }
        },
        "required": ["query"],
    }


def _make_knowledge_handler(agent_id: str, config: AppConfig):
    """Build a search_knowledge handler bound to one agent's corpus.

    Runs the synchronous DB query in a short-lived session. This is the only new
    capability injected into the voice runtime; it rides the existing
    async function-calling path, so the core voice logic is untouched.
    """
    session_factory = get_session_factory()
    max_results = config.knowledge.max_results

    async def search_knowledge(query: str) -> str:
        if not query or not query.strip():
            return "No query provided."
        with session_factory() as db:
            chunks = knowledge_service.search_chunks(
                db, agent_id, query, max_results
            )
        if not chunks:
            return "No relevant information found in the knowledge base."
        blocks = []
        for i, chunk in enumerate(chunks, start=1):
            blocks.append(f"[{i}] {chunk.content.strip()}")
        return "\n\n".join(blocks)

    return search_knowledge


class SessionToolset:
    """Bundles a per-session FunctionRegistry with any MCP connections.

    Lifecycle:
      * ``build`` constructs the registry (knowledge tool + MCP tools).
      * ``registry`` is passed to the VoiceSession.
      * ``close`` tears down MCP connections when the session ends.
    """

    def __init__(self) -> None:
        self.registry = FunctionRegistry()
        self._mcp: MCPConnectionManager | None = None

    @classmethod
    async def build(
        cls,
        agent: VoiceAgent | None,
        config: AppConfig,
        base_registry: FunctionRegistry | None = None,
    ) -> "SessionToolset":
        toolset = cls()

        # Seed with any process-wide functions registered at startup.
        if base_registry is not None:
            for name, handler in base_registry._functions.items():  # noqa: SLF001
                schema = next(
                    (
                        s
                        for s in base_registry._schemas  # noqa: SLF001
                        if s.get("function", {}).get("name") == name
                    ),
                    None,
                )
                if schema is None:
                    continue
                fn = schema["function"]
                toolset.registry.register(
                    name=name,
                    handler=handler,
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                )

        if agent is None:
            return toolset

        # Knowledge retrieval tool (only when the agent has ingested chunks).
        with get_session_factory()() as db:
            if knowledge_service.has_knowledge(db, agent.id):
                toolset.registry.register(
                    name="search_knowledge",
                    handler=_make_knowledge_handler(agent.id, config),
                    description=(
                        "Search the business knowledge base for facts, policies, "
                        "pricing, hours, and product details before answering. "
                        "Always call this when the user asks something that may be "
                        "covered by company documents."
                    ),
                    parameters=_knowledge_tool_schema(),
                )
                logger.info("Agent %s: knowledge tool registered", agent.id)

        # MCP tools.
        mcp_configs = [
            {
                "server_name": tool.server_name,
                "server_url": tool.server_url,
                "command": tool.command,
                "transport": tool.transport,
                "config": tool.config,
                "tool_allowlist": tool.tool_allowlist,
                "is_enabled": tool.is_enabled,
            }
            for tool in agent.mcp_tools
        ]
        if mcp_configs:
            manager = MCPConnectionManager()
            await manager.connect_all(mcp_configs, toolset.registry)
            toolset._mcp = manager

        return toolset

    async def close(self) -> None:
        if self._mcp is not None:
            await self._mcp.close()
            self._mcp = None
