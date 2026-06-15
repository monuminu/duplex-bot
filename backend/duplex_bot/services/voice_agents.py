from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from duplex_bot.config import AppConfig
from duplex_bot.core.security import decrypt_secret, encrypt_secret
from duplex_bot.db.models import (
    VoiceAgent,
    VoiceAgentConfig,
    VoiceAgentKnowledgeFile,
    VoiceAgentMCPTool,
    VoiceAgentSecret,
)
from duplex_bot.schemas import (
    AgentSecretPayload,
    MCPToolPayload,
    VoiceAgentConfigPayload,
    VoiceAgentCreate,
    VoiceAgentDefaults,
    VoiceAgentListItem,
    VoiceAgentRead,
    VoiceAgentUpdate,
)
from duplex_bot.services import knowledge as knowledge_service

CONFIG_SECTIONS = (
    "azure_speech",
    "azure_stt",
    "azure_tts",
    "elevenlabs",
    "llm",
    "vad",
    "eot",
    "barge_in",
)

RUNTIME_KEYS = (
    "tts_provider",
    "tts_streaming_mode",
    "tts_output_chunk_ms",
    "max_call_duration_s",
    "cache_welcome_audio",
    "internal_sample_rate",
)

# Dotted paths of provider credentials that are stored encrypted, never in the
# JSON config blob. The voice runtime overlays these back onto the effective
# config when a session starts.
SECRET_FIELDS = (
    "azure_speech.subscription_key",
    "elevenlabs.api_key",
    "llm.api_key",
)


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value if item is not None]
    return value


def _public_section_dict(config: AppConfig, section: str) -> dict[str, Any]:
    data = getattr(config, section).model_dump()
    if section == "azure_speech":
        data["subscription_key"] = ""
    if section == "elevenlabs":
        data["api_key"] = ""
    if section == "llm":
        data["api_key"] = ""
    return data


def default_agent_config(base_config: AppConfig | None = None) -> VoiceAgentDefaults:
    config = base_config or AppConfig()
    payload = VoiceAgentConfigPayload(
        azure_speech=_public_section_dict(config, "azure_speech"),
        azure_stt=config.azure_stt.model_dump(),
        azure_tts=config.azure_tts.model_dump(),
        elevenlabs=_public_section_dict(config, "elevenlabs"),
        llm=_public_section_dict(config, "llm"),
        vad=config.vad.model_dump(),
        eot=config.eot.model_dump(),
        barge_in=config.barge_in.model_dump(),
        runtime={key: getattr(config, key) for key in RUNTIME_KEYS},
    )
    return VoiceAgentDefaults(
        config=payload,
        secret_fields_configured={field: False for field in SECRET_FIELDS},
    )


def _config_from_payload(payload: VoiceAgentConfigPayload) -> VoiceAgentConfig:
    values = payload.model_dump()
    return VoiceAgentConfig(**{key: _strip_none(value) for key, value in values.items()})


def _apply_config_payload(config: VoiceAgentConfig, payload: VoiceAgentConfigPayload) -> None:
    for key, value in payload.model_dump().items():
        setattr(config, key, _strip_none(value))


def _tool_from_payload(payload: MCPToolPayload) -> VoiceAgentMCPTool:
    return VoiceAgentMCPTool(**payload.model_dump())


def _apply_secrets(
    agent: VoiceAgent,
    secrets: list[AgentSecretPayload],
    config: AppConfig,
) -> None:
    """Upsert/clear encrypted provider secrets from a write payload.

    A None/empty value clears the secret. Unknown keys are ignored so the API
    surface stays bounded to SECRET_FIELDS.
    """
    existing = {s.secret_key: s for s in agent.secrets}
    for item in secrets:
        if item.key not in SECRET_FIELDS:
            continue
        if item.value is None or item.value == "":
            record = existing.get(item.key)
            if record is not None:
                agent.secrets.remove(record)
            continue
        record = existing.get(item.key)
        ciphertext = encrypt_secret(item.value, config)
        if record is None:
            agent.secrets.append(
                VoiceAgentSecret(secret_key=item.key, encrypted_value=ciphertext)
            )
        else:
            record.encrypted_value = ciphertext


def _secret_status(agent: VoiceAgent) -> dict[str, bool]:
    configured = {s.secret_key for s in agent.secrets if s.encrypted_value}
    return {field: field in configured for field in SECRET_FIELDS}


def to_read_model(agent: VoiceAgent) -> VoiceAgentRead:
    model = VoiceAgentRead.model_validate(agent)
    model.secret_fields_configured = _secret_status(agent)
    return model


def _load_agent_or_404(
    db: Session, agent_id: str, tenant_id: str | None
) -> VoiceAgent:
    query = (
        select(VoiceAgent)
        .where(VoiceAgent.id == agent_id)
        .options(
            selectinload(VoiceAgent.config),
            selectinload(VoiceAgent.mcp_tools),
            selectinload(VoiceAgent.knowledge_files),
            selectinload(VoiceAgent.secrets),
        )
    )
    if tenant_id is not None:
        query = query.where(VoiceAgent.tenant_id == tenant_id)
    agent = db.scalar(query)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice agent not found")
    return agent


def list_agents(db: Session, tenant_id: str | None = None) -> list[VoiceAgentListItem]:
    query = (
        select(VoiceAgent)
        .where(VoiceAgent.is_active.is_(True))
        .options(
            selectinload(VoiceAgent.config),
            selectinload(VoiceAgent.mcp_tools),
            selectinload(VoiceAgent.knowledge_files),
        )
        .order_by(VoiceAgent.updated_at.desc())
    )
    if tenant_id is not None:
        query = query.where(VoiceAgent.tenant_id == tenant_id)
    agents = db.scalars(query).all()
    items: list[VoiceAgentListItem] = []
    for agent in agents:
        runtime = agent.config.runtime if agent.config else {}
        llm = agent.config.llm if agent.config else {}
        items.append(
            VoiceAgentListItem(
                id=agent.id,
                name=agent.name,
                is_active=agent.is_active,
                updated_at=agent.updated_at,
                tts_provider=(runtime or {}).get("tts_provider"),
                llm_model=(llm or {}).get("model"),
                mcp_tool_count=len(agent.mcp_tools),
                knowledge_file_count=len(agent.knowledge_files),
            )
        )
    return items


def get_agent(db: Session, agent_id: str, tenant_id: str | None = None) -> VoiceAgent:
    return _load_agent_or_404(db, agent_id, tenant_id)


def create_agent(
    db: Session, payload: VoiceAgentCreate, tenant_id: str, config: AppConfig
) -> VoiceAgent:
    agent = VoiceAgent(
        tenant_id=tenant_id,
        name=payload.name,
        system_prompt=payload.system_prompt,
        welcome_message=payload.welcome_message,
        is_active=payload.is_active,
        config=_config_from_payload(payload.config),
        mcp_tools=[_tool_from_payload(tool) for tool in payload.mcp_tools],
    )
    db.add(agent)
    _apply_secrets(agent, payload.secrets, config)
    db.commit()
    return _load_agent_or_404(db, agent.id, tenant_id)


def update_agent(
    db: Session,
    agent_id: str,
    payload: VoiceAgentUpdate,
    tenant_id: str,
    config: AppConfig,
) -> VoiceAgent:
    agent = _load_agent_or_404(db, agent_id, tenant_id)
    agent.name = payload.name
    agent.system_prompt = payload.system_prompt
    agent.welcome_message = payload.welcome_message
    agent.is_active = payload.is_active
    if agent.config is None:
        agent.config = _config_from_payload(payload.config)
    else:
        _apply_config_payload(agent.config, payload.config)
    agent.mcp_tools = [_tool_from_payload(tool) for tool in payload.mcp_tools]
    _apply_secrets(agent, payload.secrets, config)
    db.commit()
    return _load_agent_or_404(db, agent.id, tenant_id)


def delete_agent(db: Session, agent_id: str, tenant_id: str) -> None:
    agent = _load_agent_or_404(db, agent_id, tenant_id)
    agent.is_active = False
    db.commit()


async def save_knowledge_files(
    db: Session,
    agent_id: str,
    files: list[UploadFile],
    storage_root: Path,
    tenant_id: str,
    config: AppConfig,
) -> list[VoiceAgentKnowledgeFile]:
    agent = _load_agent_or_404(db, agent_id, tenant_id)
    agent_dir = storage_root / agent.id
    agent_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = config.knowledge.max_file_mb * 1024 * 1024

    saved: list[VoiceAgentKnowledgeFile] = []
    for upload in files:
        record = VoiceAgentKnowledgeFile(
            agent_id=agent.id,
            file_name=upload.filename or "uploaded-file",
            content_type=upload.content_type or "",
            size_bytes=0,
            storage_path="pending",
            status="processing",
        )
        db.add(record)
        db.flush()
        target = agent_dir / record.id
        size = 0
        too_large = False
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    too_large = True
                    break
                handle.write(chunk)
        record.storage_path = str(target)
        record.size_bytes = size

        if too_large:
            record.status = "error"
            record.error = f"File exceeds {config.knowledge.max_file_mb}MB limit"
            target.unlink(missing_ok=True)
            saved.append(record)
            continue

        # Extract + chunk for retrieval. Failures are recorded but never abort
        # the upload — the file is still stored.
        try:
            chunk_count = knowledge_service.ingest_file(db, record, config)
            record.chunk_count = chunk_count
            record.status = "ready" if chunk_count > 0 else "empty"
        except Exception as exc:  # noqa: BLE001 - surfaced to the user via status
            record.status = "error"
            record.error = str(exc)[:500]
        saved.append(record)

    db.commit()
    for record in saved:
        db.refresh(record)
    return saved


def delete_knowledge_file(
    db: Session, agent_id: str, file_id: str, tenant_id: str
) -> None:
    _load_agent_or_404(db, agent_id, tenant_id)
    record = db.scalar(
        select(VoiceAgentKnowledgeFile).where(
            VoiceAgentKnowledgeFile.agent_id == agent_id,
            VoiceAgentKnowledgeFile.id == file_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found")
    path = Path(record.storage_path)
    if path.exists():
        path.unlink()
    db.delete(record)
    db.commit()


def build_effective_config(
    agent: VoiceAgent | None,
    base_config: AppConfig | None = None,
) -> AppConfig:
    """Merge a stored agent (config sections + runtime + decrypted secrets) onto
    the environment base config to produce the config a voice session runs with.
    """
    config = deepcopy(base_config or AppConfig())
    if agent is None:
        return config

    if agent.system_prompt is not None:
        config.system_prompt = agent.system_prompt
    if agent.welcome_message is not None:
        config.welcome_message = agent.welcome_message

    if agent.config is None:
        _overlay_secrets(agent, config)
        return config

    for section in CONFIG_SECTIONS:
        patch = _strip_none(getattr(agent.config, section) or {})
        if not patch:
            continue
        current = getattr(config, section)
        setattr(config, section, current.model_copy(update=patch))

    runtime = _strip_none(agent.config.runtime or {})
    for key in RUNTIME_KEYS:
        if key in runtime:
            setattr(config, key, runtime[key])

    _overlay_secrets(agent, config)
    return config


def _overlay_secrets(agent: VoiceAgent, config: AppConfig) -> None:
    """Decrypt stored provider secrets and overlay them onto the config."""
    for record in agent.secrets:
        if not record.encrypted_value:
            continue
        plaintext = decrypt_secret(record.encrypted_value, config)
        if not plaintext:
            continue
        section_name, _, field = record.secret_key.partition(".")
        section = getattr(config, section_name, None)
        if section is None or not field:
            continue
        try:
            setattr(config, section_name, section.model_copy(update={field: plaintext}))
        except (AttributeError, ValueError):
            continue
