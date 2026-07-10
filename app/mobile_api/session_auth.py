from __future__ import annotations

from app.database.db import auth_session_is_active, get_auth_session, touch_auth_session
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.security import decode_token


class AccessTokenError(ValueError):
    pass


def validate_access_token(token: str, *, touch: bool = True) -> dict:
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise AccessTokenError("Invalid token") from exc

    if payload.get("type") != "access":
        raise AccessTokenError("Invalid token type")

    username = str(payload.get("sub") or "")
    session_id = str(payload.get("sid") or "")
    if not username or not session_id:
        raise AccessTokenError("Invalid session")

    db_path = get_db_path()
    session = get_auth_session(db_path, session_id)
    if not auth_session_is_active(session, username=username):
        raise AccessTokenError("Invalid session")

    if touch:
        touch_auth_session(db_path, session_id)

    return {
        "username": username,
        "user_id": str(session.get("user_id") or ""),
        "token_type": "access",
        "session_id": session_id,
        "token_id": str(payload.get("jti") or ""),
    }
