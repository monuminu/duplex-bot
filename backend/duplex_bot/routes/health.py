from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_BROWSER_CLIENT_PATH = Path(__file__).parent.parent.parent / "scripts" / "browser_client.html"


@router.get("/", response_class=HTMLResponse)
async def browser_client() -> HTMLResponse:
    """Serve the browser voice client UI."""
    return HTMLResponse(_BROWSER_CLIENT_PATH.read_text())


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict:
    return {"status": "ready"}
