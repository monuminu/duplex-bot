from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from duplex_bot.config import AppConfig
from duplex_bot.db.models import Tenant, User
from duplex_bot.db.session import get_db
from duplex_bot.routes.deps import get_config, get_current_user
from duplex_bot.schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    TenantRead,
    UserRead,
)
from duplex_bot.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class MeResponse(UserRead):
    tenant: TenantRead


@router.get("/config")
def auth_config(config: AppConfig = Depends(get_config)) -> dict:
    """Public flags the SPA uses to render signup/login appropriately."""
    return {"allow_signup": config.auth.allow_signup}


@router.post("/signup", response_model=AuthResponse)
def signup(
    payload: SignupRequest,
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> AuthResponse:
    return auth_service.signup(db, payload, config)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> AuthResponse:
    return auth_service.login(db, payload, config)


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    tenant = db.get(Tenant, user.tenant_id)
    data = UserRead.model_validate(user).model_dump()
    return MeResponse(**data, tenant=TenantRead.model_validate(tenant))
