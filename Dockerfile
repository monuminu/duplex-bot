# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────
# Single-container build for the Voice Agent SaaS.
#
# Stage 1 builds the Next.js SPA into a static export.
# Stage 2 installs the Python backend and copies the SPA in, so the whole
# product runs as ONE container on ONE port with ZERO external dependencies
# (embedded SQLite + auto-generated secrets under /data).
#
# Build:  docker build -t voiceagent .
# Run:    docker run -p 8000:8000 -v voiceagent-data:/data voiceagent
# Open:   http://localhost:8000
# ─────────────────────────────────────────────────────────────────────

# ── Stage 1: frontend (static export) ────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
# Build same-origin: no NEXT_PUBLIC_* needed — the SPA derives API/WS URLs from
# window.location at runtime, so the image is portable across any host/domain.
RUN npm run build


# ── Stage 2: backend + bundled SPA ───────────────────────────────────
FROM python:3.11-slim AS runtime

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app/backend

# Install dependencies first (cached layer) using only the lockfiles.
COPY backend/pyproject.toml backend/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Copy backend source and install the project itself.
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Bundle the built SPA where spa.py looks for it (backend/frontend_dist).
COPY --from=frontend /app/frontend/out ./frontend_dist

# Persistent state (SQLite DB, secret key, uploaded knowledge files).
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)" || exit 1

# One process serves the SPA, REST API, and voice WebSocket.
CMD ["python", "-m", "duplex_bot.main"]
