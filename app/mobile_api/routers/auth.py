from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.database.db import (
    clear_auth_login_failures,
    count_auth_login_failures,
    create_auth_session,
    get_or_seed_operator_user,
    record_auth_login_failure,
    revoke_auth_session,
    revoke_auth_sessions_for_username,
    rotate_auth_session_refresh,
)
from app.mobile_api.auth import get_current_user
from app.mobile_api.audit import record_audit_event
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.private_assets import clear_asset_access_cookie, set_asset_access_cookie
from app.mobile_api.public_mode import is_public_request
from app.mobile_api.schemas import (
    ErrorResponse,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.mobile_api.security import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_refresh_token,
    refresh_token_expires_at,
)
from app.mobile_api.session_cookies import (
    clear_refresh_session_cookies,
    new_csrf_token,
    refresh_token_from_request,
    require_csrf,
    set_refresh_session_cookies,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)

    def _since(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=self.window_seconds)).isoformat()

    def is_limited(self, key: str) -> bool:
        return (
            count_auth_login_failures(get_db_path(), rate_limit_key=key, since=self._since())
            >= self.max_attempts
        )

    def record_failure(self, key: str, *, username: str = "", client_host: str = "") -> None:
        record_auth_login_failure(
            get_db_path(),
            rate_limit_key=key,
            username=username,
            client_host=client_host,
        )

    def reset(self, key: str) -> None:
        clear_auth_login_failures(get_db_path(), rate_limit_key=key)


login_rate_limiter = LoginRateLimiter(
    mobile_settings.login_rate_limit_attempts,
    mobile_settings.login_rate_limit_window_seconds,
)


def _login_rate_limit_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}:{username.strip().lower()}"


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "") or request.headers.get("X-Correlation-ID", "")


def _user_agent(request: Request) -> str:
    return request.headers.get("User-Agent", "")


def _create_session_tokens(username: str, request: Request) -> tuple[str, str, str, str]:
    session_id = uuid4().hex
    refresh_family_id = uuid4().hex
    refresh_expires_at = refresh_token_expires_at()
    operator_user = get_or_seed_operator_user(get_db_path(), username)
    user_id = str(operator_user.get("id") or "")
    refresh_token = create_refresh_token(
        data={"sub": username},
        session_id=session_id,
        token_id=uuid4().hex,
        expires_at=refresh_expires_at,
    )
    create_auth_session(
        get_db_path(),
        session_id=session_id,
        username=username,
        user_id=user_id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        refresh_family_id=refresh_family_id,
        expires_at=refresh_expires_at.isoformat(),
        client_host=_client_host(request),
        user_agent=_user_agent(request),
        request_id=_request_id(request),
    )
    access_token = create_access_token(
        data={"sub": username},
        session_id=session_id,
        token_id=uuid4().hex,
    )
    return session_id, access_token, refresh_token, user_id


@router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
async def login(form_data: LoginRequest, request: Request, response: Response):
    """Login with username and password."""
    rate_limit_key = _login_rate_limit_key(request, form_data.username)
    if login_rate_limiter.is_limited(rate_limit_key):
        record_audit_event(
            event_type="auth_login_lockout",
            severity="warning",
            source="auth",
            message="Login blocked by rate limit",
            request=request,
            details={"username": form_data.username.strip(), "result": "rate_limited"},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts",
        )

    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        login_rate_limiter.record_failure(
            rate_limit_key,
            username=form_data.username.strip(),
            client_host=_client_host(request),
        )
        record_audit_event(
            event_type="auth_login_failure",
            severity="warning",
            source="auth",
            message="Login failed",
            request=request,
            details={"username": form_data.username.strip(), "result": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_rate_limiter.reset(rate_limit_key)
    session_id, access_token, refresh_token, user_id = _create_session_tokens(user.username, request)
    secure = is_public_request(request)
    set_asset_access_cookie(response, access_token, secure=secure)
    set_refresh_session_cookies(
        response,
        refresh_token,
        csrf_token=new_csrf_token(),
        secure=secure,
    )
    record_audit_event(
        event_type="session_create",
        severity="info",
        source="auth",
        message="Session created",
        request=request,
        actor_user_id=user_id,
        owner_user_id=user_id,
        details={"username": user.username, "session_id": session_id, "result": "success"},
    )
    record_audit_event(
        event_type="auth_login_success",
        severity="info",
        source="auth",
        message="Login succeeded",
        request=request,
        actor_user_id=user_id,
        owner_user_id=user_id,
        details={"username": user.username, "result": "success"},
    )
    return TokenResponse(access_token=access_token)


@router.post("/logout", response_model=dict)
async def logout(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    """Logout user (client should discard tokens)."""
    session_id = current_user.get("session_id", "")
    revoked = revoke_auth_session(get_db_path(), session_id)
    secure = is_public_request(request)
    clear_asset_access_cookie(response, secure=secure)
    clear_refresh_session_cookies(response, secure=secure)
    record_audit_event(
        event_type="session_revoke",
        severity="info",
        source="auth",
        message="Session revoked",
        request=request,
        details={
            "username": current_user.get("username", ""),
            "session_id": session_id,
            "revoked_count": revoked,
            "scope": "current",
        },
    )
    record_audit_event(
        event_type="auth_logout",
        severity="info",
        source="auth",
        message="Logout requested",
        request=request,
        details={"username": current_user.get("username", ""), "result": "success"},
    )
    return {"message": "Successfully logged out"}


@router.post("/logout-all", response_model=dict)
async def logout_all(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    """Revoke all active sessions for the single operator."""
    username = current_user.get("username", "")
    revoked = revoke_auth_sessions_for_username(get_db_path(), username)
    secure = is_public_request(request)
    clear_asset_access_cookie(response, secure=secure)
    clear_refresh_session_cookies(response, secure=secure)
    record_audit_event(
        event_type="session_revoke",
        severity="info",
        source="auth",
        message="All sessions revoked",
        request=request,
        details={
            "username": username,
            "session_id": current_user.get("session_id", ""),
            "revoked_count": revoked,
            "scope": "all",
        },
    )
    record_audit_event(
        event_type="auth_logout_all",
        severity="info",
        source="auth",
        message="Logout all requested",
        request=request,
        details={"username": username, "revoked_count": revoked, "result": "success"},
    )
    return {"message": "Successfully logged out all sessions", "revoked": revoked}


@router.get("/me", response_model=UserResponse, responses={401: {"model": ErrorResponse}})
async def read_current_user(current_user: dict = Depends(get_current_user)):
    """Get current user info."""
    return UserResponse(username=current_user["username"])


@router.post("/refresh", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
async def refresh_token(request: Request, response: Response):
    """Refresh access token using refresh token."""
    current_refresh_token = refresh_token_from_request(request)
    if not current_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "refresh_required", "message": "Session refresh is unavailable"},
        )
    require_csrf(request)
    try:
        payload = decode_token(current_refresh_token)
    except ValueError:
        record_audit_event(
            event_type="session_refresh_rejected",
            severity="warning",
            source="auth",
            message="Refresh token rejected",
            request=request,
            details={"result": "invalid_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    username = payload.get("sub")
    session_id = str(payload.get("sid") or "")
    if payload.get("type") != "refresh" or username is None or not session_id:
        record_audit_event(
            event_type="session_refresh_rejected",
            severity="warning",
            source="auth",
            message="Refresh token rejected",
            request=request,
            details={
                "username": str(username or ""),
                "session_id": session_id,
                "result": "malformed_refresh_token",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    next_expires_at = refresh_token_expires_at()
    next_refresh_token = create_refresh_token(
        data={"sub": str(username)},
        session_id=session_id,
        token_id=uuid4().hex,
        expires_at=next_expires_at,
    )
    rotate_status, session = rotate_auth_session_refresh(
        get_db_path(),
        session_id=session_id,
        current_refresh_token_hash=hash_refresh_token(current_refresh_token),
        next_refresh_token_hash=hash_refresh_token(next_refresh_token),
        next_expires_at=next_expires_at.isoformat(),
    )
    if rotate_status != "rotated":
        event_type = (
            "session_refresh_reuse"
            if rotate_status == "reuse_detected"
            else "session_refresh_rejected"
        )
        record_audit_event(
            event_type=event_type,
            severity="warning",
            source="auth",
            message="Refresh token rejected",
            request=request,
            details={
                "username": str(username or ""),
                "session_id": session_id,
                "result": rotate_status,
            },
            actor_user_id=str(session.get("user_id") or "") if session else "",
            owner_user_id=str(session.get("user_id") or "") if session else "",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    access_token = create_access_token(
        data={"sub": str(username)},
        session_id=session_id,
        token_id=uuid4().hex,
    )
    secure = is_public_request(request)
    set_asset_access_cookie(response, access_token, secure=secure)
    set_refresh_session_cookies(
        response,
        next_refresh_token,
        csrf_token=new_csrf_token(),
        secure=secure,
    )
    record_audit_event(
        event_type="session_refresh_success",
        severity="info",
        source="auth",
        message="Session refreshed",
        request=request,
        actor_user_id=str(session.get("user_id") or "") if session else "",
        owner_user_id=str(session.get("user_id") or "") if session else "",
        details={
            "username": session.get("username", str(username)) if session else str(username),
            "session_id": session_id,
            "result": "success",
        },
    )
    return TokenResponse(access_token=access_token)
