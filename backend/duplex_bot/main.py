from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from duplex_bot.config import AppConfig
from duplex_bot.db.session import init_db
from duplex_bot.llm.function_calling import FunctionRegistry
from duplex_bot.routes import auth, health, voice_agents, ws
from duplex_bot.routes.spa import mount_spa
from duplex_bot.vad.silero import SileroVAD

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — load models on startup, clean up on shutdown."""
    config = AppConfig()
    logger.info("Loading configuration...")

    # Zero-config bootstrap: create the database + tables on first boot.
    init_db()

    # Load VAD model (shared across sessions)
    vad_model = SileroVAD()
    await vad_model.load()
    logger.info("Silero VAD model loaded")

    # Load NAMO turn detector at startup (shared across sessions)
    eot_classifier = None
    if config.eot.enabled and config.eot.detector_type == "namo":
        from duplex_bot.llm.namo_turn_detector import NamoSemanticClassifier
        eot_classifier = NamoSemanticClassifier(language=config.eot.namo_language)
        await eot_classifier.load()
        logger.info("NAMO turn detector model loaded")

    # Create shared function registry (register process-wide functions here)
    function_registry = FunctionRegistry()

    # Configure WebSocket routes with shared state
    ws.configure(config, vad_model, function_registry, eot_classifier)

    logger.info("Duplex Bot ready on %s:%d", config.host, config.port)
    logger.info("WebSocket endpoints:")
    logger.info("  Browser: ws://%s:%d/ws/browser", config.host, config.port)
    logger.info("  Exotel:  ws://%s:%d/ws/exotel", config.host, config.port)

    yield

    logger.info("Shutting down...")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    config = AppConfig()
    app = FastAPI(
        title="Duplex Bot",
        description="Multi-tenant full-duplex voice agent SaaS (cascaded STT → LLM → TTS)",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router)
    app.include_router(voice_agents.router)
    app.include_router(ws.router, tags=["websocket"])

    # Serve the built SPA from the same origin so the whole product ships as a
    # single container. No-op when the frontend build is not present.
    mount_spa(app, config)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    config = AppConfig()
    uvicorn.run(
        "duplex_bot.main:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )
