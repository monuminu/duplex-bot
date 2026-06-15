from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from duplex_bot.config import AppConfig
from duplex_bot.db.models import User
from duplex_bot.db.session import get_db
from duplex_bot.routes.deps import get_config, get_current_user
from duplex_bot.schemas import (
    KnowledgeFileRead,
    VoiceAgentCreate,
    VoiceAgentDefaults,
    VoiceAgentListItem,
    VoiceAgentRead,
    VoiceAgentUpdate,
)
from duplex_bot.services import voice_agents as service

router = APIRouter(prefix="/api/voice-agents", tags=["voice-agents"])


@router.get("", response_model=list[VoiceAgentListItem])
def list_voice_agents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[VoiceAgentListItem]:
    return service.list_agents(db, tenant_id=user.tenant_id)


@router.get("/defaults", response_model=VoiceAgentDefaults)
def get_voice_agent_defaults(
    user: User = Depends(get_current_user),
) -> VoiceAgentDefaults:
    return service.default_agent_config()


@router.post("", response_model=VoiceAgentRead, status_code=status.HTTP_201_CREATED)
def create_voice_agent(
    payload: VoiceAgentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
):
    agent = service.create_agent(db, payload, tenant_id=user.tenant_id, config=config)
    return service.to_read_model(agent)


@router.get("/{agent_id}", response_model=VoiceAgentRead)
def get_voice_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = service.get_agent(db, agent_id, tenant_id=user.tenant_id)
    return service.to_read_model(agent)


@router.put("/{agent_id}", response_model=VoiceAgentRead)
def update_voice_agent(
    agent_id: str,
    payload: VoiceAgentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
):
    agent = service.update_agent(
        db, agent_id, payload, tenant_id=user.tenant_id, config=config
    )
    return service.to_read_model(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    service.delete_agent(db, agent_id, tenant_id=user.tenant_id)


@router.post("/{agent_id}/knowledge-files", response_model=list[KnowledgeFileRead])
async def upload_knowledge_files(
    agent_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> list[KnowledgeFileRead]:
    storage_root = Path(config.knowledge_storage_dir)
    return await service.save_knowledge_files(
        db, agent_id, files, storage_root, tenant_id=user.tenant_id, config=config
    )


@router.delete(
    "/{agent_id}/knowledge-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_knowledge_file(
    agent_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    service.delete_knowledge_file(db, agent_id, file_id, tenant_id=user.tenant_id)
