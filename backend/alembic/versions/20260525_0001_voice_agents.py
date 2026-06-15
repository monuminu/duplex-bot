"""create multi-tenant voice agent tables

Revision ID: 20260525_0001
Revises:
Create Date: 2026-05-25

Note: for the default single-container (SQLite) deployment, tables are created
automatically at startup via ``init_db()`` — running Alembic is optional. These
migrations exist for managed-Postgres deployments that prefer explicit
migrations. They are dialect-aware: the ``duplex`` schema is only used on
Postgres.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON
from sqlalchemy.dialects import postgresql

revision = "20260525_0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "duplex"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _schema() -> str | None:
    return None if _is_sqlite() else SCHEMA


def _json():
    # JSONB on Postgres, plain JSON elsewhere — mirrors db.models.JSONColumn.
    return JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    schema = _schema()
    if not _is_sqlite():
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        schema=schema,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], [_fk("tenants")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema=schema,
    )
    op.create_table(
        "voice_agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], [_fk("tenants")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index("ix_voice_agents_tenant_id", "voice_agents", ["tenant_id"], schema=schema)
    op.create_index("ix_voice_agents_updated_at", "voice_agents", ["updated_at"], schema=schema)

    op.create_table(
        "voice_agent_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("azure_speech", _json(), nullable=True),
        sa.Column("azure_stt", _json(), nullable=True),
        sa.Column("azure_tts", _json(), nullable=True),
        sa.Column("elevenlabs", _json(), nullable=True),
        sa.Column("llm", _json(), nullable=True),
        sa.Column("vad", _json(), nullable=True),
        sa.Column("eot", _json(), nullable=True),
        sa.Column("barge_in", _json(), nullable=True),
        sa.Column("runtime", _json(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], [_fk("voice_agents")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
        schema=schema,
    )
    op.create_table(
        "voice_agent_secrets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("secret_key", sa.String(length=120), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], [_fk("voice_agents")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "secret_key", name="uq_agent_secret_key"),
        schema=schema,
    )
    op.create_table(
        "voice_agent_mcp_tools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("server_name", sa.String(length=160), nullable=False),
        sa.Column("server_url", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("transport", sa.String(length=40), nullable=False, server_default="streamable_http"),
        sa.Column("config", _json(), nullable=True),
        sa.Column("tool_allowlist", _json(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], [_fk("voice_agents")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_table(
        "voice_agent_knowledge_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], [_fk("voice_agents")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_table(
        "voice_agent_knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], [_fk("voice_agent_knowledge_files")], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index(
        "ix_voice_agent_knowledge_chunks_agent_id",
        "voice_agent_knowledge_chunks",
        ["agent_id"],
        schema=schema,
    )


def _fk(table: str) -> str:
    schema = _schema()
    return f"{schema}.{table}.id" if schema else f"{table}.id"


def downgrade() -> None:
    schema = _schema()
    op.drop_table("voice_agent_knowledge_chunks", schema=schema)
    op.drop_table("voice_agent_knowledge_files", schema=schema)
    op.drop_table("voice_agent_mcp_tools", schema=schema)
    op.drop_table("voice_agent_secrets", schema=schema)
    op.drop_table("voice_agent_configs", schema=schema)
    op.drop_index("ix_voice_agents_updated_at", table_name="voice_agents", schema=schema)
    op.drop_index("ix_voice_agents_tenant_id", table_name="voice_agents", schema=schema)
    op.drop_table("voice_agents", schema=schema)
    op.drop_table("users", schema=schema)
    op.drop_table("tenants", schema=schema)
    if not _is_sqlite():
        op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
