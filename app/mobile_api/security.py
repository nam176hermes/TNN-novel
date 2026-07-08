from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.mobile_api.config import mobile_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def authenticate_user(username: str, password: str) -> Any:
    from app.mobile_api.config import mobile_settings
    if username == mobile_settings.admin_username:
        hashed_password = get_password_hash(mobile_settings.admin_password)
        if verify_password(password, hashed_password):
            return type("User", (), {"username": username})()
    return None


def create_long_lived_token(data: dict, years: int = 10) -> str:
    """Create a long-lived API key (default 10 years). For extension/auto-import use."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=365 * years)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, mobile_settings.secret_key, algorithm=mobile_settings.algorithm)


def _token_id() -> str:
    return secrets.token_urlsafe(24)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expires_at(expires_delta: timedelta | None = None) -> datetime:
    return datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=mobile_settings.refresh_token_expire_days)
    )


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
    *,
    session_id: str = "",
    token_id: str = "",
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=mobile_settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access", "jti": token_id or _token_id()})
    if session_id:
        to_encode["sid"] = session_id
    return jwt.encode(to_encode, mobile_settings.secret_key, algorithm=mobile_settings.algorithm)


def create_refresh_token(
    data: dict,
    expires_delta: timedelta | None = None,
    *,
    session_id: str = "",
    token_id: str = "",
    expires_at: datetime | None = None,
) -> str:
    to_encode = data.copy()
    expire = expires_at or refresh_token_expires_at(expires_delta)
    to_encode.update({"exp": expire, "type": "refresh", "jti": token_id or _token_id()})
    if session_id:
        to_encode["sid"] = session_id
    return jwt.encode(to_encode, mobile_settings.secret_key, algorithm=mobile_settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, mobile_settings.secret_key, algorithms=[mobile_settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc
