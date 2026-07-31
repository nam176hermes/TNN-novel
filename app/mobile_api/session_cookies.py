from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

from app.mobile_api.config import mobile_settings


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_refresh_session_cookies(
    response: Response,
    refresh_token: str,
    *,
    csrf_token: str,
    secure: bool,
) -> None:
    max_age = max(60, mobile_settings.refresh_token_expire_days * 24 * 60 * 60)
    response.set_cookie(
        key=mobile_settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        max_age=max_age,
        path="/api/auth",
        samesite="lax",
        secure=secure,
    )
    response.set_cookie(
        key=mobile_settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        max_age=max_age,
        path="/",
        samesite="lax",
        secure=secure,
    )


def clear_refresh_session_cookies(response: Response, *, secure: bool) -> None:
    for name, httponly, path in (
        (mobile_settings.refresh_cookie_name, True, "/api/auth"),
        (mobile_settings.csrf_cookie_name, False, "/"),
    ):
        response.delete_cookie(
            key=name,
            path=path,
            httponly=httponly,
            samesite="lax",
            secure=secure,
        )


def refresh_token_from_request(request: Request) -> str:
    return request.cookies.get(mobile_settings.refresh_cookie_name, "")


def require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(mobile_settings.csrf_cookie_name, "")
    header_token = request.headers.get(mobile_settings.csrf_header_name, "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_rejected", "message": "Request verification failed"},
        )
