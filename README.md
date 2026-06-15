# VoiceAgent — Full-Duplex Voice Agent SaaS

A multi-tenant platform for building production-grade, full-duplex voice agents
for customer support. Small businesses sign up, build a voice agent (prompt +
providers + tools + knowledge), bring their own provider keys, and talk to it
live in the browser.

The full-duplex voice core (VAD → STT → LLM → TTS with barge-in, auto-truncation,
async function-calling that survives interrupts, semantic end-of-turn detection,
and false-positive resume) is unchanged — this is the SaaS shell around it.

## Deploy: one container, zero config

The entire product — SPA, REST API, and voice WebSocket — ships as a **single
container** that serves everything from **one port** with **no external
dependencies**. State persists in an embedded SQLite database under `/data`.

```bash
docker build -t voiceagent .
docker run -p 8000:8000 -v voiceagent-data:/data voiceagent
# open http://localhost:8000  → sign up → build an agent → talk to it
```

or with Compose:

```bash
docker compose up --build
```

Because the SPA derives its API/WebSocket URLs from the browser's own origin and
the database/secret key auto-initialize on first boot, the **same image is
portable across any cloud** (Azure Container Apps, Cloud Run, ECS, Fly, Render,
a bare VM) with nothing to configure. Mount a volume at `/data` to persist.

### Scaling out (optional)

To use a managed Postgres instead of embedded SQLite, set one env var — the same
image switches over, no code change. `postgres://` / `postgresql://` DSNs are
auto-normalized to the psycopg driver:

```bash
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db" \
  -e SECRET_KEY="<stable-shared-secret>" \
  voiceagent
```

Pin `SECRET_KEY` in production so JWTs and encrypted provider credentials survive
redeploys and are shared across replicas.

## What a tenant gets

- **Accounts & workspaces** — email/password signup + login (JWT). Every agent is
  scoped to the tenant; data is isolated between customers.
- **Voice agent builder** — name, system prompt, welcome message, STT/TTS provider
  selection, VAD/turn-detection/barge-in tuning, and runtime controls.
- **Bring-your-own keys** — per-agent provider credentials (OpenAI/Azure/ElevenLabs)
  stored **encrypted at rest** (Fernet). The API only ever reports whether a key is
  set, never its value.
- **Knowledge base** — upload PDF/Word/Markdown/text; files are parsed, chunked, and
  indexed. The agent answers from them through a built-in `search_knowledge` tool.
- **MCP tools** — connect Model Context Protocol servers (HTTP/SSE/stdio). Their
  tools are loaded per call and run through the existing async function-calling path,
  so they survive barge-in.
- **Playground** — connect a mic and talk to any saved agent live.

## Project structure

```text
backend/   FastAPI: voice core (unchanged) + auth, tenants, agents, knowledge, MCP, SPA serving
frontend/  Next.js SPA (static export): login, agent builder, playground
Dockerfile, docker-compose.yml   single-container build
```

## Local development (split mode)

Backend:

```bash
cd backend
uv sync --extra dev
uv run python -m duplex_bot.main      # serves API + WS on :8000 (SQLite auto-created under ./data)
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env.local            # points at http://localhost:8000 for split dev
npm run dev                           # http://localhost:3000
```

The optional Alembic migrations live in `backend/alembic` for managed-Postgres
deployments. For the default SQLite container, tables are created automatically
at startup — no migration step needed.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run lint && npm run build
```
