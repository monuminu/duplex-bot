# Duplex Bot

Full-duplex voice agent with a cascaded **VAD → STT → LLM → TTS** architecture, running over bidirectional WebSocket connections.

## Features

- **Full-Duplex Conversation** — simultaneous listen + speak with barge-in support
- **Auto-Truncation** — on interrupt, only the portion the user actually heard is kept in conversation history
- **Async Function Calling** — LLM tool calls execute asynchronously and survive barge-in; results trigger follow-up turns
- **Speculative Response Pre-generation** — pre-caches LLM responses for likely short user inputs ("yes", "no", "okay") during silence
- **Semantic End-of-Turn Detection** — two-tier: hard silence threshold (700ms) + lightweight LLM classifier
- **Noise Suppression** — filters filler words, noise artifacts, and low-confidence transcriptions
- **End-to-End Observability** — Langfuse integration with per-stage latency metrics and session-level traces
- **Provider Flexibility** — abstract bases for STT, TTS, LLM, and telephony adapters; swap providers via config

## Architecture

```
WebSocket ──► Adapter (Exotel/Browser) ──► Session Orchestrator
                                                │
                ┌───────────────────────────────┤
                │           │           │       │
              VAD ──► STT ──► LLM ──► TTS ──► Output
                │               │
           Interrupt        FunctionExecutor (async, survives barge-in)
                │
         TruncationTracker ──► ConversationHistory
```

Each WebSocket connection = one `VoiceSession` with its own asyncio task graph and queue pipeline.

## Supported Providers

| Component | Providers |
|-----------|-----------|
| **VAD** | Silero VAD (ONNX Runtime, no PyTorch) |
| **STT** | Azure Fast Transcription API (REST, batch per speech segment) |
| **LLM** | Any OpenAI-compatible endpoint (OpenAI, Azure OpenAI, Groq, Together, local vLLM) |
| **TTS** | Azure Speech SDK (thread-bridged streaming), ElevenLabs (WebSocket streaming) |
| **Adapters** | Browser (binary PCM + JSON), Exotel (Twilio-style Media Streams protocol) |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management

### Setup

```bash
# Clone and install
git clone <repo-url> && cd duplex-bot/backend
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your API keys (Azure Speech, LLM, etc.)
```

### Download VAD Model

```bash
mkdir -p duplex_bot/models
curl -L -o duplex_bot/models/silero_vad.onnx \
  https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx
```

### Run

```bash
uv run python -m duplex_bot.main
```

The server starts at `http://localhost:8000` with two WebSocket endpoints:

| Endpoint | Description |
|----------|-------------|
| `ws://localhost:8000/ws/browser` | Browser client (16kHz PCM + JSON) |
| `ws://localhost:8000/ws/exotel` | Exotel telephony (8kHz mulaw + JSON events) |

### Frontend Playground

Start the Next.js app from `../frontend`, open `http://localhost:3000/playground`, click
**Connect**, and speak. The client captures microphone audio via Web Audio API and streams it to
`ws://localhost:8000/ws/browser`. You'll see your transcriptions and the agent's responses in the UI.

## Configuration

All configuration is via environment variables or `.env` file, using nested delimiter `__` for grouped settings.

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `SYSTEM_PROMPT` | (conversational assistant) | LLM system prompt |
| `TTS_PROVIDER` | `azure` | TTS backend: `azure` or `elevenlabs` |
| `TTS_OUTPUT_CHUNK_MS` | `32` | Outbound TTS frame size for lower playback start latency |
| **VAD / Turn Detection** | | |
| `VAD__MIN_SILENCE_DURATION_MS` | `250` | Silence required before committing a speech segment |
| `VAD__TRAILING_SILENCE_MS` | `100` | Maximum trailing silence kept in STT audio |
| `EOT__ENABLED` | `false` | Enable semantic end-of-turn checks instead of immediate post-STT turns |
| `EOT__SILENCE_THRESHOLD_MS` | `700` | Hard silence threshold when semantic EOT is enabled |
| `EOT__SEMANTIC_CHECK_AFTER_MS` | `300` | Delay before semantic EOT checks when enabled |
| **Azure Speech** | | |
| `AZURE_SPEECH__SUBSCRIPTION_KEY` | | Azure Speech Services key |
| `AZURE_SPEECH__REGION` | `eastus` | Azure region |
| `AZURE_STT__LANGUAGE` | `en-US` | STT language |
| `AZURE_TTS__VOICE_NAME` | `en-US-JennyNeural` | TTS voice |
| **ElevenLabs** | | |
| `ELEVENLABS__API_KEY` | | ElevenLabs API key |
| `ELEVENLABS__VOICE_ID` | | ElevenLabs voice ID |
| `ELEVENLABS__MODEL_ID` | `eleven_turbo_v2_5` | ElevenLabs model |
| **LLM** | | |
| `LLM__BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `LLM__API_KEY` | | API key |
| `LLM__MODEL` | `gpt-4o` | Model name |
| `LLM__TEMPERATURE` | `0.7` | Sampling temperature |
| `LLM__MAX_TOKENS` | `1024` | Max output tokens |
| **Langfuse** | | |
| `LANGFUSE__PUBLIC_KEY` | | Langfuse public key |
| `LANGFUSE__SECRET_KEY` | | Langfuse secret key |
| `LANGFUSE__HOST` | `https://cloud.langfuse.com` | Langfuse host |

## Project Structure

```
duplex_bot/
├── main.py                 # FastAPI app + lifespan
├── config.py               # Pydantic Settings (all config)
├── core/
│   ├── session.py          # VoiceSession orchestrator (the heart)
│   ├── pipeline.py         # Sentence splitting, accumulation
│   ├── events.py           # Internal event dataclasses
│   ├── audio.py            # PCM resample, WAV encoding, mulaw
│   └── conversation.py     # Chat history + truncation
├── vad/
│   ├── base.py             # Abstract VAD
│   ├── silero.py           # Silero ONNX implementation
│   └── stream.py           # State machine: IDLE→SPEECH→ENDING→IDLE
├── stt/
│   ├── base.py             # Abstract STT
│   └── azure_fast.py       # Azure Fast Transcription (REST)
├── llm/
│   ├── base.py             # Abstract LLM
│   ├── openai_compat.py    # OpenAI-compatible streaming SSE
│   ├── function_calling.py # Async executor + registry
│   └── turn_detector.py    # Semantic end-of-turn classifier
├── tts/
│   ├── base.py             # Abstract TTS
│   ├── azure_speech.py     # Azure Speech SDK (thread-bridged)
│   └── elevenlabs.py       # ElevenLabs streaming (WebSocket)
├── adapters/
│   ├── base.py             # Abstract TelephonyAdapter
│   ├── exotel.py           # Exotel/Twilio Media Streams
│   └── browser.py          # Browser WebSocket (PCM + JSON)
├── observability/
│   ├── tracer.py           # Langfuse trace/span management
│   └── metrics.py          # Metric name constants
├── strategies/
│   ├── noise_filter.py     # Semantic noise suppression
│   ├── truncation.py       # Auto-truncation tracker
│   └── speculation.py      # Speculative response pre-generation
└── routes/
    ├── ws.py               # WebSocket endpoint /ws/{adapter_name}
    └── health.py           # Health check endpoints
```

## Key Metrics (Langfuse)

Each voice session is a Langfuse trace. The headline metric is **EIBC → FSB** (End of Input Buffer Committed → First Speech Byte) — the full round-trip latency from user done speaking to agent audio starting to play.

Per-stage latencies: `stt_latency`, `llm_ttft`, `llm_total_latency`, `tts_ttfb`, `interrupt_latency`

Session-level: `turn_count`, `barge_in_count`, `session_duration_ms`, `speculation_hit_rate`

## Adding a New Provider

Each provider type has an abstract base class. To add a new one:

1. **STT**: Subclass `stt/base.py` → implement `transcribe(audio, sample_rate, language) → Transcript`
2. **TTS**: Subclass `tts/base.py` → implement `synthesize_stream(text, voice) → AsyncIterator[TTSAudioChunk]`
3. **LLM**: Subclass `llm/base.py` → implement `generate_stream(messages, tools, temperature) → AsyncIterator[LLMResponseChunk]`
4. **Adapter**: Subclass `adapters/base.py` → implement `on_connect`, `receive`, `send_audio`, `send_clear`, `send_mark`

Then wire it in `routes/ws.py` and `config.py`.

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check .

# Run with auto-reload
uv run python -m duplex_bot.main
```

## License

MIT License.
