from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from duplex_bot.config import AppConfig
from duplex_bot.llm.function_calling import FunctionRegistry
from duplex_bot.routes import health, ws
from duplex_bot.vad.silero import SileroVAD

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — load models on startup, clean up on shutdown."""
    config = AppConfig()
    logger.info("Loading configuration...")

    # Load VAD model (shared across sessions)
    vad_model = SileroVAD()
    await vad_model.load()
    logger.info("Silero VAD model loaded")

    # Create shared function registry (register your functions here)
    function_registry = FunctionRegistry()
    # Example:
    # async def get_weather(city: str) -> dict:
    #     return {"temperature": 22, "condition": "sunny"}
    # function_registry.register(
    #     "get_weather",
    #     get_weather,
    #     "Get current weather for a city",
    #     {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    # )

    # Configure WebSocket routes with shared state
    ws.configure(config, vad_model, function_registry)

    logger.info("Duplex Bot ready on %s:%d", config.host, config.port)
    logger.info("WebSocket endpoints:")
    logger.info("  Browser: ws://%s:%d/ws/browser", config.host, config.port)
    logger.info("  Exotel:  ws://%s:%d/ws/exotel", config.host, config.port)

    yield

    logger.info("Shutting down...")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Duplex Bot",
        description="Full-duplex voice agent with cascaded STT → LLM → TTS architecture",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router, tags=["health"])
    app.include_router(ws.router, tags=["websocket"])
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    config = AppConfig()
    uvicorn.run(
        "duplex_bot.main:app",
        host=config.host,
        port=config.port,
        reload=True,
        log_level="info",
    )
