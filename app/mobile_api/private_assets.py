from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from fastapi import HTTPException, Request, Response, status

from app.mobile_api.config import auth_bypass_enabled, mobile_settings
from app.mobile_api.session_auth import AccessTokenError, validate_access_token


def set_asset_access_cookie(response: Response, access_token: str, *, secure: bool | None = None) -> None:
    response.set_cookie(
        key=mobile_settings.asset_cookie_name,
        value=access_token,
        httponly=True,
        max_age=max(60, mobile_settings.access_token_expire_minutes * 60),
        path="/",
        samesite="lax",
        secure=mobile_settings.public_deploy if secure is None else secure,
    )


def clear_asset_access_cookie(response: Response, *, secure: bool | None = None) -> None:
    response.delete_cookie(
        key=mobile_settings.asset_cookie_name,
        path="/",
        samesite="lax",
        secure=mobile_settings.public_deploy if secure is None else secure,
    )


def asset_request_has_traversal(path: str) -> bool:
    decoded_path = unquote(path)
    return "\x00" in decoded_path or "\\" in decoded_path or any(
        part == ".." for part in PurePosixPath(decoded_path).parts
    )


def asset_token_from_request(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return request.cookies.get(mobile_settings.asset_cookie_name, "")


def authenticate_asset_request(request: Request) -> None:
    if auth_bypass_enabled():
        return
    token = asset_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        validate_access_token(token)
    except AccessTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def resolve_private_asset(root: Path, asset_path: str) -> Path:
    decoded_path = unquote(asset_path).strip()
    if not decoded_path or asset_request_has_traversal(decoded_path):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid asset path")

    relative_path = PurePosixPath(decoded_path)
    if relative_path.is_absolute():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid asset path")

    root_path = root.resolve()
    candidate = (root_path / Path(*relative_path.parts)).resolve()
    if candidate == root_path or root_path not in candidate.parents:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid asset path")
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return candidate
