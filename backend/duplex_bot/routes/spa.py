from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from duplex_bot.config import AppConfig

logger = logging.getLogger(__name__)

# Reserved API/runtime prefixes that the SPA fallback must never intercept.
_RESERVED_PREFIXES = ("/api", "/ws", "/health", "/ready", "/docs", "/openapi.json", "/redoc")


def _resolve_dist_dir(config: AppConfig) -> Path | None:
    """Locate the built frontend directory, if present.

    Order of preference:
      1. FRONTEND_DIST_DIR env override
      2. ./frontend_dist next to the backend (Docker image layout)
      3. ../frontend/out (local `next build` static export)
    """
    candidates: list[Path] = []
    if config.frontend_dist_dir:
        candidates.append(Path(config.frontend_dist_dir))
    here = Path(__file__).resolve()
    backend_root = here.parent.parent.parent  # .../backend
    candidates.append(backend_root / "frontend_dist")
    candidates.append(backend_root.parent / "frontend" / "out")

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            return candidate
    return None


def mount_spa(app: FastAPI, config: AppConfig) -> None:
    """Serve the static SPA from FastAPI with history-API fallback.

    When no build is present (e.g. split local dev), this is a no-op and the
    backend serves only the API/WS — the Next dev server handles the UI.
    """
    dist_dir = _resolve_dist_dir(config)
    if dist_dir is None:
        logger.info("No frontend build found; serving API only.")
        return

    logger.info("Serving SPA from %s", dist_dir)

    # Hashed Next.js assets live under _next/. Mount them directly for caching.
    next_static = dist_dir / "_next"
    if next_static.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_static)), name="next-static")

    index_file = dist_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> Response:
        path = "/" + full_path
        if any(path == p or path.startswith(p + "/") for p in _RESERVED_PREFIXES):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Serve a real file when it exists (assets, favicon, statically
        # exported html pages), otherwise fall back to index.html so client
        # routing (e.g. /login, /voice-agents) works on refresh.
        candidate = (dist_dir / full_path).resolve()
        try:
            candidate.relative_to(dist_dir.resolve())
        except ValueError:
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if full_path and candidate.is_file():
            return FileResponse(candidate)

        html_variant = dist_dir / f"{full_path}.html"
        if full_path and html_variant.is_file():
            return FileResponse(html_variant)

        return FileResponse(index_file)
