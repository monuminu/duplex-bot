from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from duplex_bot.adapters.base import TelephonyAdapter
from duplex_bot.adapters.browser import BrowserAdapter
from duplex_bot.adapters.exotel import ExotelAdapter
from duplex_bot.config import AppConfig
from duplex_bot.core.session import VoiceSession
from duplex_bot.llm.function_calling import FunctionRegistry
from duplex_bot.llm.openai_compat import OpenAICompatibleLLM
from duplex_bot.observability.tracer import SessionTracer
from duplex_bot.stt.azure_fast import AzureFastTranscription
from duplex_bot.tts.azure_speech import AzureSpeechTTS
from duplex_bot.tts.base import TTSBase
from duplex_bot.tts.elevenlabs import ElevenLabsTTS
from duplex_bot.vad.silero import SileroVAD
from duplex_bot.vad.stream import VADStream

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level state (set during app startup)
_config: AppConfig | None = None
_vad_model: SileroVAD | None = None
_function_registry: FunctionRegistry | None = None


def configure(config: AppConfig, vad_model: SileroVAD, function_registry: FunctionRegistry | None = None) -> None:
    """Configure the WebSocket routes with shared state."""
    global _config, _vad_model, _function_registry
    _config = config
    _vad_model = vad_model
    _function_registry = function_registry


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


def _create_tts(config: AppConfig) -> TTSBase:
    """Create a TTS provider based on config."""
    if config.tts_provider == "elevenlabs":
        return ElevenLabsTTS(config.elevenlabs)
    else:
        return AzureSpeechTTS(config.azure_speech, config.azure_tts)


@router.websocket("/ws/{adapter_name}")
async def websocket_endpoint(websocket: WebSocket, adapter_name: str) -> None:
    """Main WebSocket endpoint for voice sessions.

    URL format: /ws/{adapter_name}
    - /ws/browser — Browser/UI client
    - /ws/exotel — Exotel telephony
    """
    assert _config is not None, "WebSocket routes not configured. Call configure() first."
    assert _vad_model is not None, "VAD model not loaded."

    await websocket.accept()

    session_id = str(uuid4())

    try:
        adapter = _create_adapter(adapter_name)
    except ValueError as e:
        logger.error("Invalid adapter: %s", e)
        await websocket.close(code=1008, reason=str(e))
        return

    # Create per-session components
    vad_stream = VADStream(_vad_model, _config.vad, session_id)
    stt = AzureFastTranscription(_config.azure_speech, _config.azure_stt)
    llm = OpenAICompatibleLLM(_config.llm)
    tts = _create_tts(_config)

    tracer = None
    if _config.langfuse.enabled and _config.langfuse.public_key:
        tracer = SessionTracer(_config.langfuse)

    session = VoiceSession(
        session_id=session_id,
        adapter=adapter,
        vad_stream=vad_stream,
        stt=stt,
        llm=llm,
        tts=tts,
        config=_config,
        function_registry=_function_registry,
        tracer=tracer,
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
        await stt.close()
        await llm.close()
        if tracer:
            tracer.flush()
