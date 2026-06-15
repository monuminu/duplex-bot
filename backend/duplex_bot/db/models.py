from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Portable JSON column: JSONB on Postgres, plain JSON on SQLite/others.
# This keeps the same models working in a zero-config single container (SQLite)
# and against a managed Postgres without any code changes.
JSONColumn = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Declarative base with no hardcoded schema.

    On Postgres the session sets ``search_path`` to the ``duplex`` schema, so
    tables land there without qualifying every model. On SQLite there is no
    schema concept and everything lives in the single file database.
    """


def _new_uuid() -> str:
    return str(uuid4())


class Tenant(Base):
    """A customer account. Every agent and user belongs to exactly one tenant."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    users: Mapped[list[User]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    agents: Mapped[list[VoiceAgent]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base):
    """A login identity scoped to a tenant."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class VoiceAgent(Base):
    __tablename__ = "voice_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant | None] = relationship(back_populates="agents")
    config: Mapped[VoiceAgentConfig] = relationship(
        back_populates="agent", cascade="all, delete-orphan", uselist=False
    )
    mcp_tools: Mapped[list[VoiceAgentMCPTool]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    knowledge_files: Mapped[list[VoiceAgentKnowledgeFile]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    secrets: Mapped[list[VoiceAgentSecret]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class VoiceAgentConfig(Base):
    __tablename__ = "voice_agent_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    azure_speech: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    azure_stt: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    azure_tts: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    elevenlabs: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    llm: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    vad: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    eot: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    barge_in: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    runtime: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)

    agent: Mapped[VoiceAgent] = relationship(back_populates="config")


class VoiceAgentSecret(Base):
    """Encrypted provider credential for an agent.

    ``secret_key`` is a dotted path like ``llm.api_key`` or
    ``azure_speech.subscription_key``. ``encrypted_value`` is a Fernet token —
    never stored or returned in plaintext. The API only ever reports whether a
    secret is configured, not its value.
    """

    __tablename__ = "voice_agent_secrets"
    __table_args__ = (
        UniqueConstraint("agent_id", "secret_key", name="uq_agent_secret_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False
    )
    secret_key: Mapped[str] = mapped_column(String(120), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped[VoiceAgent] = relationship(back_populates="secrets")


class VoiceAgentMCPTool(Base):
    __tablename__ = "voice_agent_mcp_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False
    )
    server_name: Mapped[str] = mapped_column(String(160), nullable=False)
    server_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    transport: Mapped[str] = mapped_column(String(40), nullable=False, default="streamable_http")
    config: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)
    tool_allowlist: Mapped[list | None] = mapped_column(JSONColumn, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped[VoiceAgent] = relationship(back_populates="mcp_tools")


class VoiceAgentKnowledgeFile(Base):
    __tablename__ = "voice_agent_knowledge_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("voice_agents.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="stored")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    agent: Mapped[VoiceAgent] = relationship(back_populates="knowledge_files")
    chunks: Mapped[list[VoiceAgentKnowledgeChunk]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class VoiceAgentKnowledgeChunk(Base):
    """A retrievable text chunk extracted from an uploaded knowledge file."""

    __tablename__ = "voice_agent_knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("voice_agent_knowledge_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    file: Mapped[VoiceAgentKnowledgeFile] = relationship(back_populates="chunks")
