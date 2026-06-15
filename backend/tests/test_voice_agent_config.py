from __future__ import annotations

from duplex_bot.config import AppConfig
from duplex_bot.db.models import VoiceAgent, VoiceAgentConfig
from duplex_bot.services.voice_agents import build_effective_config


def test_effective_config_overrides_agent_fields_and_keeps_env_defaults() -> None:
    base = AppConfig(
        system_prompt="env prompt",
        welcome_message="env welcome",
        tts_provider="azure",
    )
    agent = VoiceAgent(
        name="Support",
        system_prompt="agent prompt",
        welcome_message=None,
        config=VoiceAgentConfig(
            azure_stt={"language": "hi-IN", "api_version": None},
            azure_tts={},
            runtime={"tts_provider": "elevenlabs", "tts_output_chunk_ms": None},
        ),
    )

    effective = build_effective_config(agent, base)

    assert effective.system_prompt == "agent prompt"
    assert effective.welcome_message == "env welcome"
    assert effective.azure_stt.language == "hi-IN"
    assert effective.azure_stt.api_version == base.azure_stt.api_version
    assert effective.tts_provider == "elevenlabs"
    assert effective.tts_output_chunk_ms == base.tts_output_chunk_ms

