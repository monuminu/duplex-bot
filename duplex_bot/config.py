from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSpeechConfig(BaseModel):
    subscription_key: str = ""
    region: str = "eastus"
    resource_name: str = ""
    resource_id: str = ""
    auth_mode: str = "entra"  # "key" or "entra"


class AzureSTTConfig(BaseModel):
    language: str = "en-US"
    api_version: str = "2025-10-15"


class AzureTTSConfig(BaseModel):
    voice_name: str = "en-US-JennyNeural"
    output_format: str = "Raw16Khz16BitMonoPcm"


class ElevenLabsConfig(BaseModel):
    api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_turbo_v2_5"
    output_format: str = "pcm_16000"
    optimize_streaming_latency: int = 3


class LLMConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 1024
    api_style: str = "openai"  # "openai" or "azure"
    api_format: str = "responses"  # "chat_completions", "responses", or "realtime"


class VADConfig(BaseModel):
    activation_threshold: float = 0.46
    sample_rate: int = 16000
    min_speech_duration_ms: int = 300
    max_speech_duration_s: int = 20
    # Lower values reduce turn latency but can cut off users who pause mid-thought.
    min_silence_duration_ms: int = 250
    trailing_silence_ms: int = 100
    window_size_samples: int = 512
    speech_pad_ms: int = 200
    prefix_padding_ms: int = 200
    chunk_size_ms: int = 32


class EndOfTurnConfig(BaseModel):
    enabled: bool = False
    detector_type: str = "llm"
    silence_threshold_ms: int = 700
    semantic_check_after_ms: int = 300
    semantic_confidence_threshold: float = 0.7
    namo_language: str | None = "en"


class TTSProviderType(str):
    AZURE = "azure"
    ELEVENLABS = "elevenlabs"


class BargeInConfig(BaseModel):
    false_positive_resume_enabled: bool = True
    false_positive_resume_timeout_s: float = 5.0
    stt_confirmation_timeout_s: float = 8.0


class LangfuseConfig(BaseModel):
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"
    enabled: bool = True


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    host: str = "0.0.0.0"
    port: int = 8000

    azure_speech: AzureSpeechConfig = AzureSpeechConfig()
    azure_stt: AzureSTTConfig = AzureSTTConfig()
    azure_tts: AzureTTSConfig = AzureTTSConfig()
    elevenlabs: ElevenLabsConfig = ElevenLabsConfig()
    llm: LLMConfig = LLMConfig()
    vad: VADConfig = VADConfig()
    eot: EndOfTurnConfig = EndOfTurnConfig()
    langfuse: LangfuseConfig = LangfuseConfig()
    barge_in: BargeInConfig = BargeInConfig()

    tts_provider: str = "azure"
    tts_streaming_mode: str = "incremental"  # "incremental" (token-by-token) or "sentence" (accumulate sentences)
    tts_output_chunk_ms: int = 32

    max_call_duration_s: int = 1800  # 30 minutes

    system_prompt: str = "You are a helpful voice assistant. Keep your responses concise and conversational."
    welcome_message: str = ""
    cache_welcome_audio: bool = True
    internal_sample_rate: int = 16000
