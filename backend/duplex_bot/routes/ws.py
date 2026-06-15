from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import SQLAlchemyError

from duplex_bot.adapters.base import TelephonyAdapter
from duplex_bot.adapters.browser import BrowserAdapter
from duplex_bot.adapters.exotel import ExotelAdapter
from duplex_bot.config import AppConfig
from duplex_bot.core.azure_token import AzureTokenProvider
from duplex_bot.core.session import VoiceSession
from duplex_bot.db.session import get_session_factory
from duplex_bot.db.models import VoiceAgent
from duplex_bot.llm.base import LLMBase
from duplex_bot.llm.function_calling import FunctionRegistry
from duplex_bot.llm.openai_responses import OpenAIResponsesLLM
from duplex_bot.llm.realtime import OpenAIRealtimeLLM
from duplex_bot.llm.session_tools import SessionToolset
from duplex_bot.observability.tracer import SessionTracer
from duplex_bot.stt.azure_fast import AzureFastTranscription
from duplex_bot.tts.azure_speech import AzureSpeechTTS
from duplex_bot.tts.base import TTSBase
from duplex_bot.tts.elevenlabs import ElevenLabsTTS
from duplex_bot.services.voice_agents import build_effective_config, get_agent
from duplex_bot.vad.silero import SileroVAD
from duplex_bot.vad.stream import VADStream

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level state (set during app startup)
_config: AppConfig | None = None
_vad_model: SileroVAD | None = None
_function_registry: FunctionRegistry | None = None
_eot_classifier = None


def configure(config: AppConfig, vad_model: SileroVAD, function_registry: FunctionRegistry | None = None, eot_classifier=None) -> None:
    """Configure the WebSocket routes with shared state."""
    global _config, _vad_model, _function_registry, _eot_classifier
    _config = config
    _vad_model = vad_model
    _function_registry = function_registry
    _eot_classifier = eot_classifier


def _create_adapter(adapter_name: str) -> TelephonyAdapter:
    """Create a telephony adapter by name."""
    adapters = {
        "exotel": ExotelAdapter,
        "browser": BrowserAdapter,
    }
    adapter_cls = adapters.get(adapter_name)
    if adapter_cls is None:
        raise ValueError(f"Unknown adapter: {adapter_name}. Available: {list(adapters.keys())}")
    return adapter_cls()


def _create_llm(config: AppConfig, token_provider: AzureTokenProvider | None = None) -> LLMBase:
    """Create an LLM provider based on config.api_format."""
    if config.llm.api_format == "realtime":
        return OpenAIRealtimeLLM(config.llm, token_provider)
    return OpenAIResponsesLLM(config.llm, token_provider)


def _create_tts(config: AppConfig, token_provider: AzureTokenProvider | None = None) -> TTSBase:
    """Create a TTS provider based on config."""
    if config.tts_provider == "elevenlabs":
        return ElevenLabsTTS(config.elevenlabs)
    else:
        return AzureSpeechTTS(config.azure_speech, config.azure_tts, token_provider)


def _tenant_from_token(token: str | None) -> str | None:
    """Best-effort tenant extraction from a JWT passed as a WS query param.

    WebSockets can't carry Authorization headers from the browser, so the SPA
    appends ?token=<jwt>. When present and valid, the agent lookup is scoped to
    that tenant. Telephony adapters (no token) fall through unscoped.
    """
    if not token or _config is None:
        return None
    try:
        from duplex_bot.core.security import decode_access_token

        payload = decode_access_token(token, _config)
        return payload.get("tenant_id")
    except Exception:  # noqa: BLE001 - invalid token => unscoped lookup
        return None


def _resolve_session(
    base_config: AppConfig, agent_id: str | None, tenant_id: str | None
) -> tuple[AppConfig, VoiceAgent | None]:
    """Load the agent (if any) and compute its effective runtime config.

    Returns the effective config plus the loaded agent (with relationships
    eagerly loaded so the per-session toolset can be built after the DB session
    closes). When no agent is bound, the environment config is used as-is.
    """
    if not agent_id:
        return base_config, None

    session_factory = get_session_factory()
    with session_factory() as db:
        agent = get_agent(db, agent_id, tenant_id)
        effective = build_effective_config(agent, base_config)
        # Trigger relationship loads while the session is open.
        _ = (agent.mcp_tools, agent.knowledge_files)
        db.expunge(agent)
        return effective, agent


@router.websocket("/ws/{adapter_name}")
async def websocket_endpoint(
    websocket: WebSocket,
    adapter_name: str,
    agent_id: str | None = Query(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Main WebSocket endpoint for voice sessions.

    URL format: /ws/{adapter_name}
    - /ws/browser — Browser/UI client
    - /ws/exotel — Exotel telephony
    """
    assert _config is not None, "WebSocket routes not configured. Call configure() first."
    assert _vad_model is not None, "VAD model not loaded."

    await websocket.accept()

    session_id = str(uuid4())
    tenant_id = _tenant_from_token(token)

    try:
        adapter = _create_adapter(adapter_name)
    except ValueError as e:
        logger.error("Invalid adapter: %s", e)
        await websocket.close(code=1008, reason=str(e))
        return

    try:
        session_config, agent = _resolve_session(_config, agent_id, tenant_id)
    except SQLAlchemyError:
        logger.exception("Failed to load voice agent config: %s", agent_id)
        await websocket.close(code=1011, reason="Failed to load voice agent config")
        return
    except Exception as e:
        logger.error("Invalid voice agent: %s", e)
        await websocket.close(code=1008, reason="Voice agent not found")
        return

    # Acquire a shared Azure token for this session (used by STT, TTS, LLM)
    token_provider: AzureTokenProvider | None = None
    if session_config.azure_speech.auth_mode != "key":
        token_provider = AzureTokenProvider(
            use_managed_identity=session_config.azure_speech.use_managed_identity,
            managed_identity_client_id=session_config.azure_speech.managed_identity_client_id,
        )
        await token_provider.initialize()

    # Build the per-session toolset (knowledge retrieval + MCP tools) layered on
    # top of the process-wide function registry. This is the only injection into
    # the voice runtime — the core pipeline is unchanged.
    try:
        toolset = await SessionToolset.build(agent, session_config, _function_registry)
    except Exception:
        logger.exception("Failed to build session toolset for agent %s", agent_id)
        toolset = SessionToolset()  # empty registry; voice still works

    # Create per-session components
    vad_stream = VADStream(_vad_model, session_config.vad, session_id)
    stt = AzureFastTranscription(
        session_config.azure_speech, session_config.azure_stt, token_provider
    )
    llm = _create_llm(session_config, token_provider)
    tts = _create_tts(session_config, token_provider)

    tracer = None
    if session_config.langfuse.enabled and session_config.langfuse.public_key:
        tracer = SessionTracer(session_config.langfuse)

    session = VoiceSession(
        session_id=session_id,
        adapter=adapter,
        vad_stream=vad_stream,
        stt=stt,
        llm=llm,
        tts=tts,
        config=session_config,
        function_registry=toolset.registry,
        tracer=tracer,
        eot_classifier=_eot_classifier,
    )

    try:
        await session.run(websocket)
    except WebSocketDisconnect:
        logger.info("Session %s disconnected", session_id)
    except Exception:
        logger.exception("Session %s failed", session_id)
    finally:
        await session.shutdown()
        # Clean up per-session resources
        await toolset.close()
        await stt.close()
        await llm.close()
        if tracer:
            tracer.flush()
