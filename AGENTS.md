# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `duplex_bot/`. The main entrypoint is `duplex_bot/main.py`, configuration is centralized in `duplex_bot/config.py`, and the voice pipeline is split by concern: `core/`, `vad/`, `stt/`, `llm/`, `tts/`, `adapters/`, `routes/`, `strategies/`, and `observability/`. Browser test assets live in `scripts/`. Tests belong in `tests/`; keep new automated tests there even if you also use one-off utility scripts.

## Build, Test, and Development Commands
Use `uv` for dependency management.

- `uv sync` installs runtime dependencies.
- `uv sync --extra dev` installs pytest and Ruff.
- `uv run python -m duplex_bot.main` starts the FastAPI/WebSocket server on `localhost:8000`.
- `uv run pytest` runs the test suite.
- `uv run ruff check .` runs linting.

If you add new developer workflows, document them in `README.md` and keep examples runnable from the repo root.

## Coding Style & Naming Conventions
Target Python 3.11+ and follow the existing style: 4-space indentation, type hints, small focused modules, and `from __future__ import annotations` in package modules. Ruff enforces a `100` character line length. Use `snake_case` for functions, variables, and module names; use `PascalCase` for classes and config models. Keep provider-specific implementations in the appropriate package, for example `duplex_bot/tts/azure_speech.py`.

## Testing Guidelines
Pytest is configured in `pyproject.toml` with `asyncio_mode = "auto"` and `tests/` as the test root. Name new files `test_*.py`, especially for pipeline, adapter, and provider boundary behavior. Add focused async tests for queue flow, interruption handling, and config parsing when touching those areas. Run `uv run pytest` before opening a PR.

## Commit & Pull Request Guidelines
Recent history uses short, lowercase, task-focused subjects such as `adding fixes in sound`. Keep commit titles brief and specific; prefer clearer imperative phrasing like `fix sound resume handling`. PRs should include a concise description, affected modules, config changes, and test evidence. Include screenshots or logs when changing browser or WebSocket behavior.

## Security & Configuration Tips
Configuration is loaded from `.env` via `AppConfig` using nested keys such as `AZURE_SPEECH__REGION` and `LLM__MODEL`. Do not commit secrets, account identifiers, or generated credentials. Large local model assets belong under `duplex_bot/models/` and should be referenced, not duplicated elsewhere.
