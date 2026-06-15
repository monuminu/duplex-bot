from __future__ import annotations

import secrets
from pathlib import Path

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureSpeechConfig(BaseModel):
    subscription_key: str = ""
    region: str = "eastus"
    resource_name: str = ""
    resource_id: str = ""
    auth_mode: str = "entra"  # "key" or "entra"
    # For Entra auth: allow DefaultAzureCredential to use a managed identity.
    # Keep False for local dev (uses `az login`); set True when deployed to
    # Azure (Container Apps / App Service / AKS / VM) so the workload identity
    # is used. Optionally pin a user-assigned identity via its client id.
    use_managed_identity: bool = False
    managed_identity_client_id: str = ""


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
    min_silence_duration_ms: int = 500
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
    poll_interval_ms: int = 100
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


class AuthConfig(BaseModel):
    """SaaS authentication / multi-tenancy settings."""

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    allow_signup: bool = True
    # When True, the very first signup becomes an admin and additional signups
    # are blocked unless invited. Kept simple for single-container deployments.
    first_user_is_admin: bool = True


class KnowledgeConfig(BaseModel):
    """Knowledge-base ingestion + retrieval settings."""

    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150
    max_results: int = 4
    max_file_mb: int = 25


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
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
    auth: AuthConfig = AuthConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()

    tts_provider: str = "azure"
    tts_streaming_mode: str = "incremental"  # "incremental" (token-by-token) or "sentence" (accumulate sentences)
    tts_output_chunk_ms: int = 32

    max_call_duration_s: int = 1800  # 30 minutes

    system_prompt: str = "You are a helpful voice assistant. Keep your responses concise and conversational."
    welcome_message: str = ""
    cache_welcome_audio: bool = True
    internal_sample_rate: int = 16000

    # ── SaaS / deployment ────────────────────────────────────────────
    # data_dir holds all mutable state for a zero-config single container:
    # the SQLite database, the auto-generated secret key, and uploaded files.
    # Mount a volume here to persist across container restarts.
    data_dir: str = "data"
    # When empty (default), an embedded SQLite database under data_dir is used,
    # so the product runs with zero external dependencies. Set DATABASE_URL to a
    # Postgres DSN (postgresql+psycopg://...) to use a managed database instead.
    database_url: str = ""
    # When empty (default), a secret is generated once and persisted under
    # data_dir so JWTs and encrypted secrets survive restarts. Set SECRET_KEY in
    # production to control it explicitly (and share it across replicas).
    secret_key: str = ""
    knowledge_storage_dir: str = ""
    # Comma-separated list, or "*" to allow any origin. The SPA is served from the
    # same origin in production, so CORS is only needed for local split dev.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Directory holding the built frontend (static export). When present, the SPA
    # is served by FastAPI so the whole product runs as a single container.
    frontend_dist_dir: str = ""

    @model_validator(mode="after")
    def _resolve_derived_paths(self) -> "AppConfig":
        data_dir = Path(self.data_dir)

        if not self.secret_key:
            self.secret_key = _load_or_create_secret(data_dir)

        if not self.database_url:
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = (data_dir / "duplex_bot.db").resolve()
            self.database_url = f"sqlite:///{db_path}"
        else:
            self.database_url = _normalize_database_url(self.database_url)

        if not self.knowledge_storage_dir:
            self.knowledge_storage_dir = str(data_dir / "knowledge_base")

        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [origin.strip() for origin in value.split(",") if origin.strip()]


def _normalize_database_url(url: str) -> str:
    """Normalize cloud-provided DSNs to SQLAlchemy 2.0 driver URLs.

    Many platforms (Heroku, Render, Azure, Railway) inject ``postgres://`` or
    ``postgresql://`` DSNs. SQLAlchemy 2.0 needs an explicit driver, so we map
    these onto ``postgresql+psycopg://`` (psycopg 3). This is what makes the
    same image portable across clouds with only an env-var change.
    """
    url = url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    # Rewrite bare postgresql:// (no +driver) to use psycopg 3.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _load_or_create_secret(data_dir: Path) -> str:
    """Return a stable secret key, generating + persisting one on first run.

    This keeps the product zero-config: JWT signing keys and the Fernet
    encryption key for stored provider credentials survive restarts without the
    operator having to set anything.
    """
    secret_path = data_dir / "secret.key"
    try:
        if secret_path.exists():
            existing = secret_path.read_text().strip()
            if existing:
                return existing
        data_dir.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48)
        secret_path.write_text(generated)
        secret_path.chmod(0o600)
        return generated
    except OSError:
        # Read-only filesystem and no SECRET_KEY provided: fall back to an
        # ephemeral secret so the app still boots (sessions reset on restart).
        return secrets.token_urlsafe(48)
