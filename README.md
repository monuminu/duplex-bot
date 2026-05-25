# Duplex Bot Monorepo

Full-duplex voice agent with a FastAPI backend and a Next.js enterprise playground.

## Structure

```text
backend/   FastAPI voice agent, WebSocket adapters, tests, and Python config
frontend/  Next.js app for the VoiceAgent playground and future console screens
```

## Backend

```bash
cd backend
uv sync --extra dev
uv run python -m duplex_bot.main
```

The browser WebSocket endpoint is `ws://localhost:8000/ws/browser`.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The playground runs at `http://localhost:3000/playground` and connects to
`NEXT_PUBLIC_BACKEND_WS_URL` when set, otherwise `ws://localhost:8000/ws/browser`.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run lint && npm run build
```
