from __future__ import annotations

import re
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from duplex_bot.config import AppConfig
from duplex_bot.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from duplex_bot.db.models import Tenant, User
from duplex_bot.schemas import AuthResponse, LoginRequest, SignupRequest, TenantRead, UserRead


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


def _unique_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    suffix = 1
    while db.scalar(select(Tenant.id).where(Tenant.slug == candidate)) is not None:
        suffix += 1
        candidate = f"{slug}-{suffix}"
    return candidate


def _auth_response(user: User, tenant: Tenant, config: AppConfig) -> AuthResponse:
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, config=config)
    return AuthResponse(
        access_token=token,
        user=UserRead.model_validate(user),
        tenant=TenantRead.model_validate(tenant),
    )


def signup(db: Session, payload: SignupRequest, config: AppConfig) -> AuthResponse:
    if not config.auth.allow_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Signups are disabled"
        )

    email = payload.email.lower().strip()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    role = "admin" if (config.auth.first_user_is_admin and user_count == 0) else "owner"

    company = (payload.company_name or payload.full_name or email.split("@")[0]).strip()
    tenant = Tenant(
        id=str(uuid4()),
        name=company or "My Workspace",
        slug=_unique_slug(db, company or email.split("@")[0]),
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)
    return _auth_response(user, tenant, config)


def login(db: Session, payload: LoginRequest, config: AppConfig) -> AuthResponse:
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account is missing a workspace",
        )
    return _auth_response(user, tenant, config)
