from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.mobile_api.config import auth_bypass_enabled, mobile_settings
from app.mobile_api.session_auth import AccessTokenError, validate_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_bypass_user() -> dict:
    user_id = ""
    try:
        from app.database.db import get_or_seed_operator_user
        from app.mobile_api.dependencies import get_db_path

        operator_user = get_or_seed_operator_user(get_db_path(), mobile_settings.admin_username)
        user_id = str(operator_user.get("id") or "")
    except Exception:
        user_id = ""
    return {
        "username": mobile_settings.admin_username,
        "user_id": user_id,
        "token_type": "auth_disabled",
        "session_id": "auth-disabled",
        "token_id": "auth-disabled",
    }


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    state_user = getattr(request.state, "user", None)
    if isinstance(state_user, dict) and state_user.get("username"):
        return state_user
    if auth_bypass_enabled():
        return get_auth_bypass_user()
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = credentials.credentials
    try:
        return validate_access_token(token)
    except AccessTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["username"] != mobile_settings.admin_username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
