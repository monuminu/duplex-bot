from __future__ import annotations

import asyncio

import pytest

from duplex_bot.config import AppConfig
from duplex_bot.core.events import AudioChunk, LLMResponseChunk, TTSAudioChunk
from duplex_bot.core.session import VoiceSession
from duplex_bot.vad.stream import SpeechEnded, VADStream


class FakeVAD:
    def __init__(self, probabilities: list[float]):
        self._probabilities = probabilities
        self.reset_count = 0

    async def process_chunk(self, chunk: bytes, sample_rate: int) -> float:
        return self._probabilities.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class FakeAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.clear_count = 0

    async def send_clear(self, websocket) -> None:
        self.clear_count += 1


class FakeSTT:
    async def warmup(self) -> None:
        pass


class FakeLLM:
    async def generate_stream(self, messages: list[dict], tools=None, temperature=None):
        if False:
            yield None

    async def classify_end_of_turn(self, transcript: str, context: list[dict]) -> float:
        return 1.0


class FakeTTSSession:
    async def synthesize_stream_incremental(self, text_stream):
        async for _ in text_stream:
            pass
        if False:
            yield None

    async def synthesize_stream(self, text: str):
        if False:
            yield None

    async def close(self) -> None:
        pass


class FakeTTS:
    def create_session(self) -> FakeTTSSession:
        return FakeTTSSession()


def make_session(config: AppConfig | None = None, llm=None, tts=None) -> VoiceSession:
    config = config or AppConfig(_env_file=None)
    return VoiceSession(
        session_id="test",
        adapter=FakeAdapter(),
        vad_stream=object(),
        stt=FakeSTT(),
        llm=llm or FakeLLM(),
        tts=tts or FakeTTS(),
        config=config,
    )


class BlockingLLM(FakeLLM):
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self._release = asyncio.Event()

    async def generate_stream(self, messages: list[dict], tools=None, temperature=None):
        self.calls.append(messages)
        await self._release.wait()
        yield LLMResponseChunk(text="ok", is_final=False)
        yield LLMResponseChunk(text="", is_final=True)

    def release(self) -> None:
        self._release.set()


async def wait_for_call_count(llm: BlockingLLM, count: int) -> None:
    for _ in range(20):
        if len(llm.calls) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} LLM calls, got {len(llm.calls)}")


@pytest.mark.asyncio
async def test_turn_gate_eot_disabled_completes_immediately() -> None:
    config = AppConfig(_env_file=None)
    config.eot.enabled = False
    session = make_session(config)
    called = asyncio.Event()

    async def generate_response() -> None:
        called.set()

    async def fail_if_called(silence_ms: float, context: list[dict]) -> bool:
        raise AssertionError("semantic EOT should not run when disabled")

    session._generate_response = generate_response
    session._turn_detector.check_end_of_turn = fail_if_called

    task = asyncio.create_task(session._turn_gate_loop())
    await session._transcript_q.put("hello")
    await asyncio.wait_for(called.wait(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_turn_gate_eot_enabled_uses_detector() -> None:
    config = AppConfig(_env_file=None)
    config.eot.enabled = True
    session = make_session(config)
    called = asyncio.Event()
    checked = asyncio.Event()

    async def generate_response() -> None:
        called.set()

    async def check_end_of_turn(silence_ms: float, context: list[dict]) -> bool:
        checked.set()
        return True

    session._generate_response = generate_response
    session._turn_detector.check_end_of_turn = check_end_of_turn

    task = asyncio.create_task(session._turn_gate_loop())
    await session._transcript_q.put("hello")
    await asyncio.wait_for(checked.wait(), timeout=1)
    await asyncio.wait_for(called.wait(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_vad_trims_trailing_silence_from_emitted_segment() -> None:
    config = AppConfig(_env_file=None).vad
    config.min_speech_duration_ms = 64
    config.min_silence_duration_ms = 256
    config.trailing_silence_ms = 64
    config.speech_pad_ms = 32

    chunk = b"\x01\x00" * 512
    silence = b"\x00\x00" * 512
    vad = FakeVAD([1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    stream = VADStream(vad, config)
    emitted = None

    chunks = [
        chunk,
        chunk,
        chunk,
        silence,
        silence,
        silence,
        silence,
        silence,
        silence,
        silence,
        silence,
    ]
    for data in chunks:
        event = await stream.process(AudioChunk(data=data, sample_rate=16000))
        if isinstance(event, SpeechEnded):
            emitted = event
            break

    assert isinstance(emitted, SpeechEnded)
    assert emitted.segment.audio.endswith(silence * 2)
    assert not emitted.segment.audio.endswith(silence * 3)


def test_tts_audio_chunks_are_split_to_configured_duration() -> None:
    config = AppConfig(_env_file=None)
    config.tts_output_chunk_ms = 32
    session = make_session(config)
    audio = b"\x01\x00" * 2048
    chunk = TTSAudioChunk(
        audio=audio,
        text_span="hello",
        cumulative_duration_ms=128,
        sample_rate=16000,
    )

    split = session._split_tts_audio_chunk(chunk)

    assert [len(part.audio) for part in split] == [1024, 1024, 1024, 1024]
    assert [part.cumulative_duration_ms for part in split] == [32, 64, 96, 128]


@pytest.mark.asyncio
async def test_user_continuation_merges_while_llm_pending_before_audio() -> None:
    llm = BlockingLLM()
    session = make_session(llm=llm)

    session._commit_user_turn("Sir, I want to apply.")
    await session._generate_response()
    await wait_for_call_count(llm, 1)

    session._commit_user_turn("Credit cards, if you can.")
    await session._generate_response()
    await wait_for_call_count(llm, 2)

    messages = session._conversation.get_messages()
    user_messages = [m for m in messages if m["role"] == "user"]

    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "Sir, I want to apply. Credit cards, if you can."
    assert llm.calls[1][-1]["content"] == "Sir, I want to apply. Credit cards, if you can."

    if session._current_llm_task:
        session._current_llm_task.cancel()
        await asyncio.gather(session._current_llm_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stale_tts_queue_items_are_discarded() -> None:
    session = make_session()
    session._active_generation_id = 2

    await session._queue_tts_text(1, "old")
    await session._queue_tts_text(2, "new")

    item = await asyncio.wait_for(session._get_next_active_tts_item(), timeout=1)

    assert item.generation_id == 2
    assert item.text == "new"


def test_user_continuation_does_not_merge_after_first_audio_started() -> None:
    session = make_session()
    session._pending_user_text = "First turn."
    session._active_generation_id = 1
    session._audio_started_generation_id = 1
    session._conversation.add_user_message("First turn.")

    session._commit_user_turn("Second turn.")

    messages = session._conversation.get_messages()
    user_messages = [m for m in messages if m["role"] == "user"]

    assert [m["content"] for m in user_messages] == ["First turn.", "Second turn."]


@pytest.mark.asyncio
async def test_first_audio_waits_while_user_input_is_pending() -> None:
    session = make_session()
    session._active_generation_id = 1
    session._user_speech_active = True
    session._refresh_user_input_idle()

    wait_task = asyncio.create_task(session._wait_for_user_input_idle_before_audio(1))
    await asyncio.sleep(0)

    assert not wait_task.done()

    session._user_speech_active = False
    session._refresh_user_input_idle()

    assert await asyncio.wait_for(wait_task, timeout=1)


@pytest.mark.asyncio
async def test_first_audio_wait_aborts_when_generation_is_superseded() -> None:
    session = make_session()
    session._active_generation_id = 1
    session._user_speech_active = True
    session._refresh_user_input_idle()

    wait_task = asyncio.create_task(session._wait_for_user_input_idle_before_audio(1))
    await asyncio.sleep(0)

    session._active_generation_id = 2
    session._user_speech_active = False
    session._refresh_user_input_idle()

    assert not await asyncio.wait_for(wait_task, timeout=1)
