# Full-Duplex Voice Agent — Implementation Plan

## Context

Build a production-grade, full-duplex voice agent from scratch. The system uses a **fully cascaded architecture** (VAD → STT → LLM → TTS) running over a bidirectional WebSocket server. It must support multiple telephony providers (Exotel, browser UI) via an adapter pattern, and multiple STT/TTS providers starting with Azure. Key differentiating features: auto-truncation on barge-in, async function calling that survives interrupts, semantic end-of-turn detection, noise suppression, and speculative response pre-generation.

---

## Architecture Overview

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

Each WebSocket connection = 1 `VoiceSession` with its own asyncio task graph and queue pipeline.

---

## Tech Stack

- **Python 3.11+** with asyncio
- **FastAPI** for HTTP + WebSocket server
- **Silero VAD** via ONNX Runtime (no PyTorch)
- **Azure Fast Transcription API** for STT (REST, batch per speech segment)
- **Azure Speech SDK** for TTS (streaming via PullAudioOutputStream, bridged to asyncio)
- **OpenAI-compatible** LLM client via `httpx` (works with OpenAI, Azure OpenAI, Groq, Together, local vLLM — any endpoint that follows OpenAI's chat completions API)
- **Pydantic Settings** for all configuration
- **Langfuse** for end-to-end observability (traces, spans, metrics)
- **uv** for dependency management

---

## Directory Structure

```
duplex_bot/
├── pyproject.toml
├── .env.example
├── .gitignore
├── duplex_bot/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app + lifespan
│   ├── config.py                   # Pydantic Settings (all config)
│   ├── core/
│   │   ├── session.py              # VoiceSession orchestrator
│   │   ├── pipeline.py             # Queue wiring, task lifecycle
│   │   ├── events.py               # Internal event dataclasses
│   │   ├── audio.py                # PCM resample, WAV encoding
│   │   └── conversation.py         # Chat history + truncation
│   ├── vad/
│   │   ├── base.py                 # Abstract VAD
│   │   ├── silero.py               # Silero ONNX implementation
│   │   └── stream.py               # State machine: IDLE→SPEECH→ENDING→IDLE
│   ├── stt/
│   │   ├── base.py                 # Abstract STT
│   │   └── azure_fast.py           # Azure Fast Transcription (REST)
│   ├── llm/
│   │   ├── base.py                 # Abstract LLM
│   │   ├── openai_compat.py        # OpenAI-compatible streaming
│   │   ├── function_calling.py     # Async executor + registry
│   │   └── turn_detector.py        # Semantic end-of-turn classifier
│   ├── tts/
│   │   ├── base.py                 # Abstract TTS
│   │   ├── azure_speech.py         # Azure Speech SDK (thread-bridged)
│   │   └── elevenlabs.py           # ElevenLabs streaming TTS (WebSocket)
│   ├── adapters/
│   │   ├── base.py                 # Abstract TelephonyAdapter
│   │   ├── exotel.py               # Exotel WebSocket events
│   │   └── browser.py              # Browser/UI WebSocket
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── tracer.py               # Langfuse trace/span management
│   │   └── metrics.py              # Metric definitions and helpers
│   ├── strategies/
│   │   ├── noise_filter.py         # Semantic noise suppression
│   │   ├── truncation.py           # Auto-truncation tracker
│   │   └── speculation.py          # Speculative response pre-generation
│   └── routes/
│       ├── ws.py                   # WebSocket endpoint /ws/{adapter_name}
│       └── health.py               # Health check endpoints
├── scripts/
│   └── browser_client.html         # Browser test client (mic + playback)
└── tests/
```

---

## Key Component Designs

### 1. Telephony Adapter (extensible)
- Abstract base: `on_connect()`, `deserialize()`, `serialize_audio()`, `serialize_clear()`, `serialize_mark()`
- **Exotel**: Modeled after Twilio Media Streams protocol — JSON events (`connected`, `start`, `media`, `stop`, `mark`), base64-encoded mulaw audio in `media.payload`, 8kHz. Events have `event` field for type, `streamSid` for session tracking.
- **Browser**: Binary PCM frames (16kHz 16-bit linear PCM) + JSON control messages for non-audio events (start, stop, clear, interrupt)
- Adapter selected via URL path: `/ws/exotel`, `/ws/browser`
- Adding a new provider = one new file implementing the abstract base

### 2. VAD (Silero ONNX)
- `VADStream` state machine: `IDLE` → `SPEECH_STARTED` → `SPEECH_ACTIVE` → `SPEECH_ENDING` → `IDLE`
- On speech onset → emit `InterruptSignal` immediately (for barge-in)
- On speech end → emit complete `SpeechSegment` (buffered audio)
- Configurable thresholds: activation (0.5), min speech (250ms), min silence (300ms), prefix padding (300ms)

### 3. STT (Azure Fast Transcription)
- VAD segments speech → encode as WAV in memory → POST to Azure Fast Transcription REST API
- Batch per segment (not streaming) — simpler, accurate, and fast (~50-100ms for typical utterances)
- Abstract base allows swapping to Deepgram/ElevenLabs later

### 4. End-of-Turn Detection
- Two-tier: hard silence threshold (700ms) + semantic classifier
- Semantic classifier: lightweight LLM call to judge if user finished their thought
- Only invoked after `semantic_check_after_ms` (300ms) of silence, overlapping natural pause

### 5. Noise Suppression
- Filter filler words ("um", "uh", "hmm") and noise transcriptions ("[noise]", "[music]")
- Min word count / char length thresholds
- Applied before passing transcript to end-of-turn gate

### 6. LLM (OpenAI-compatible streaming)
- Streaming SSE parser, yields text chunks + tool call fragments
- Text split at sentence boundaries → pushed to TTS queue incrementally
- Tool calls accumulated across chunks, dispatched to async executor when complete

### 7. TTS (Azure Speech SDK + ElevenLabs)
- **Azure Speech SDK**: Synthesis runs in thread executor (SDK is synchronous). `PullAudioOutputStream` → chunks bridged to asyncio queue → streamed to WebSocket.
- **ElevenLabs**: WebSocket-based streaming TTS. Connect to ElevenLabs streaming API (`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`), send text chunks as they arrive from LLM, receive audio chunks back. Natively async — no thread bridge needed. Supports input streaming (send partial text, get audio back incrementally) for ultra-low TTFB.
- Both implement `TTSBase` — selected via config.
- Sentence-level synthesis for natural prosody.

### 8. Auto-Truncation
- `TruncationTracker` records (text, start_ms, end_ms) for each TTS segment sent
- On barge-in: calculate playback position at interrupt time
- `conversation.truncate_last_assistant(heard_text)` — only heard portion stays in history
- Playback tracking: wall-clock timing + mark events (if adapter supports them)

### 9. Async Function Calling
- `FunctionCallExecutor` with a registry of callable functions
- Function calls dispatched as independent asyncio tasks
- **Never cancelled on barge-in** — results injected into conversation when complete
- If user speaks while function is executing, their new message queues normally; function result arrives asynchronously and triggers a follow-up LLM turn

### 10. Speculative Response Generation
- During silence after agent speaks, predict likely short responses ("yes", "no", "okay")
- Pre-generate LLM responses for top-N predictions
- If user's actual input matches a prediction → use cached response (saves full LLM round-trip)
- Cancel speculation when user actually speaks

---

## Pipeline Data Flow (asyncio queues)

```
WebSocket recv → adapter.deserialize → audio_in_q → VAD → speech_q → STT → transcript_q
    → noise_filter → end_of_turn_gate → ConversationHistory → LLM (streaming)
    → tts_text_q (sentence chunks) → TTS → audio_out_q → adapter.serialize → WebSocket send

Interrupt path: VAD speech onset → interrupt_q → cancel LLM+TTS, drain queues,
    truncate conversation history, send clear to client

Function call path: LLM tool_call → function_call_q → FunctionExecutor (async)
    → result → ConversationHistory → trigger new LLM turn
```

---

## Implementation Phases

### Phase 1: Foundation
- Project scaffolding: `pyproject.toml`, dependencies, `.env.example`, `.gitignore`
- `config.py` with all Pydantic settings models
- `core/events.py` — all internal event dataclasses
- `core/audio.py` — PCM resampling, WAV header encoding

### Phase 2: VAD Pipeline
- `vad/base.py` + `vad/silero.py` (ONNX runtime)
- `vad/stream.py` — state machine with speech/silence detection, interrupt signals

### Phase 3: STT
- `stt/base.py` + `stt/azure_fast.py` (aiohttp POST, multipart WAV upload)

### Phase 4: LLM
- `llm/base.py` + `llm/openai_compat.py` (streaming SSE, tool call parsing)
- `core/conversation.py` — message management + truncation
- `llm/function_calling.py` — async executor + registry
- `llm/turn_detector.py` — semantic end-of-turn classifier

### Phase 5: TTS
- `tts/base.py` + `tts/azure_speech.py` (thread-bridged streaming)
- Sentence splitter for incremental synthesis

### Phase 6: Adapters
- `adapters/base.py` — abstract interface
- `adapters/exotel.py` — Exotel JSON events, base64/mulaw audio, 8kHz
- `adapters/browser.py` — binary PCM + JSON control, 16kHz

### Phase 7: Session Orchestrator
- `core/session.py` — VoiceSession with all pipeline tasks + queues
- `core/pipeline.py` — wiring helpers
- `routes/ws.py` — WebSocket endpoint with adapter selection
- Interrupt handler: cancel, drain, truncate, clear

### Phase 8: Advanced Strategies
- `strategies/noise_filter.py`
- `strategies/truncation.py` — TruncationTracker
- `strategies/speculation.py` — speculative pre-generation
- End-of-turn gate integration

### Phase 9: Test Client & Polish
- `scripts/browser_client.html` — Web Audio API mic capture + playback
- `main.py` — FastAPI app with lifespan, health routes
- End-to-end testing, logging, error handling

---

## Verification Plan

1. **Unit tests**: VAD state machine with synthetic audio, noise filter, truncation tracker math
2. **Integration tests**: STT with real Azure endpoint, TTS with real Azure endpoint, LLM streaming
3. **Browser test**: Open `browser_client.html`, speak, verify full round-trip (speech → transcription → LLM response → TTS playback)
4. **Barge-in test**: Speak while agent is responding, verify: audio stops, truncation correct in history
5. **Function call test**: Trigger a tool-calling conversation, interrupt during execution, verify function completes and result appears in next turn
6. **Adapter test**: Connect via Exotel simulator, verify event serialization/deserialization

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| VAD-first, then batch STT (not streaming STT) | VAD already segments speech; batch transcription of complete utterances is more accurate. Azure Fast Transcription handles 3s audio in ~50-100ms. |
| ONNX for Silero VAD (not PyTorch) | 50MB vs 2GB dependency. 4-5x faster inference. |
| Azure Speech SDK TTS via thread bridge | SDK provides streaming synthesis with low TTFB. Thread-to-asyncio bridge is reliable. |
| Sentence-level TTS | Better prosody than word-level. First sentence from LLM completes in ~200-400ms. |
| asyncio.Queue for all pipeline communication | Natural backpressure, built-in, easy to reason about. |
| Function calls survive barge-in | Prevents wasted work. Results available for next turn. |
| URL-path adapter selection | Clean routing, no message sniffing needed. |