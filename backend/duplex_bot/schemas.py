from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


JsonObject = dict[str, Any]


# ─── Auth ───────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    role: str
    tenant_id: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    tenant: TenantRead


# ─── Voice agents ───────────────────────────────────────────────────


class VoiceAgentConfigPayload(BaseModel):
    azure_speech: JsonObject | None = None
    azure_stt: JsonObject | None = None
    azure_tts: JsonObject | None = None
    elevenlabs: JsonObject | None = None
    llm: JsonObject | None = None
    vad: JsonObject | None = None
    eot: JsonObject | None = None
    barge_in: JsonObject | None = None
    runtime: JsonObject | None = None


class MCPToolPayload(BaseModel):
    server_name: str = Field(min_length=1, max_length=160)
    server_url: str | None = None
    command: str | None = None
    transport: str = "streamable_http"
    config: JsonObject | None = None
    tool_allowlist: list[str] | None = None
    is_enabled: bool = True


class AgentSecretPayload(BaseModel):
    """A provider credential to set (write-only).

    ``key`` is a dotted path like ``llm.api_key``. An empty/None ``value``
    clears the stored secret.
    """

    key: str = Field(min_length=1, max_length=120)
    value: str | None = None


class VoiceAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    system_prompt: str | None = None
    welcome_message: str | None = None
    is_active: bool = True
    config: VoiceAgentConfigPayload = Field(default_factory=VoiceAgentConfigPayload)
    mcp_tools: list[MCPToolPayload] = Field(default_factory=list)
    secrets: list[AgentSecretPayload] = Field(default_factory=list)


class VoiceAgentUpdate(VoiceAgentCreate):
    pass


class KnowledgeFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_name: str
    content_type: str
    size_bytes: int
    status: str
    chunk_count: int
    error: str | None
    created_at: datetime


class MCPToolRead(MCPToolPayload):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class VoiceAgentConfigRead(VoiceAgentConfigPayload):
    model_config = ConfigDict(from_attributes=True)


class VoiceAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    system_prompt: str | None
    welcome_message: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    config: VoiceAgentConfigRead | None
    mcp_tools: list[MCPToolRead]
    knowledge_files: list[KnowledgeFileRead]
    # Map of dotted secret key -> whether a value is stored (never the value).
    secret_fields_configured: dict[str, bool] = Field(default_factory=dict)


class VoiceAgentListItem(BaseModel):
    id: str
    name: str
    is_active: bool
    updated_at: datetime
    tts_provider: str | None
    llm_model: str | None
    mcp_tool_count: int
    knowledge_file_count: int


class VoiceAgentDefaults(BaseModel):
    config: VoiceAgentConfigPayload
    secret_fields_configured: dict[str, bool]
