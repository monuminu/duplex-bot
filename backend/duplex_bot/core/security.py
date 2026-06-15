from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from duplex_bot.config import AppConfig


# ─── Password hashing ───────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─── JWT access tokens ──────────────────────────────────────────────


def create_access_token(
    *,
    user_id: str,
    tenant_id: str,
    config: AppConfig,
    extra: dict | None = None,
) -> str:
    """Create a signed JWT for an authenticated user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=config.auth.access_token_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, config.secret_key, algorithm=config.auth.jwt_algorithm)


def decode_access_token(token: str, config: AppConfig) -> dict:
    """Decode and validate a JWT. Raises jwt exceptions on failure."""
    return jwt.decode(
        token,
        config.secret_key,
        algorithms=[config.auth.jwt_algorithm],
    )


# ─── Secret encryption (provider credentials at rest) ───────────────


@lru_cache(maxsize=4)
def _fernet_for(secret_key: str) -> Fernet:
    """Derive a stable Fernet key from the app secret key.

    Provider credentials (Azure/OpenAI/ElevenLabs keys, MCP headers) are stored
    encrypted so a database dump never leaks tenant secrets.
    """
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str, config: AppConfig) -> str:
    """Encrypt a secret value for storage. Empty values pass through."""
    if not plaintext:
        return ""
    token = _fernet_for(config.secret_key).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, config: AppConfig) -> str:
    """Decrypt a stored secret value. Returns "" on empty/invalid input."""
    if not ciphertext:
        return ""
    try:
        return _fernet_for(config.secret_key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
