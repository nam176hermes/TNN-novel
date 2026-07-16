from __future__ import annotations

import os
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv

from app.config import PROJECT_ROOT


def _ignore_dotenv() -> bool:
    return os.getenv("NOVEL_PIPELINE_IGNORE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}


if not _ignore_dotenv():
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _parse_cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


class MobileAPISettings(BaseModel):
    model_config = ConfigDict(validate_default=True)

    version: str = "0.1.0"
    host: str = os.getenv("MOBILE_API_HOST", "0.0.0.0")
    port: int = int(os.getenv("MOBILE_API_PORT", "7860"))
    public_deploy: bool = _parse_bool(os.getenv("PUBLIC_DEPLOY", "0"))
    secret_key: str = os.getenv("MOBILE_API_SECRET", "dev-secret-change-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = int(os.getenv("MOBILE_API_ACCESS_MINUTES", "60"))
    refresh_token_expire_days: int = int(os.getenv("MOBILE_API_REFRESH_DAYS", "14"))
    asset_cookie_name: str = os.getenv("MOBILE_API_ASSET_COOKIE_NAME", "novel_asset_access")
    upload_max_bytes: int = int(os.getenv("MOBILE_API_UPLOAD_MAX_BYTES", str(100 * 1024 * 1024)))
    admin_username: str = os.getenv("MOBILE_API_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("MOBILE_API_ADMIN_PASSWORD", "change_me")
    login_rate_limit_attempts: int = int(os.getenv("MOBILE_API_LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
    login_rate_limit_window_seconds: int = int(os.getenv("MOBILE_API_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
    job_stale_after_seconds: int = int(os.getenv("JOB_STALE_AFTER_SECONDS", "300"))
    job_heartbeat_interval_seconds: float = float(os.getenv("JOB_HEARTBEAT_INTERVAL_SECONDS", "30"))
    import_job_max_chapters: int = Field(
        default=int(os.getenv("IMPORT_JOB_MAX_CHAPTERS", "200")),
        gt=0,
        le=5_000,
    )
    auth_session_retention_days: int = Field(
        default=int(os.getenv("AUTH_SESSION_RETENTION_DAYS", "30")),
        gt=0,
    )
    auth_session_retention_max_rows: int = Field(
        default=int(os.getenv("AUTH_SESSION_RETENTION_MAX_ROWS", "5000")),
        gt=0,
    )
    auth_login_failure_retention_days: int = Field(
        default=int(os.getenv("AUTH_LOGIN_FAILURE_RETENTION_DAYS", "30")),
        gt=0,
    )
    auth_login_failure_retention_max_rows: int = Field(
        default=int(os.getenv("AUTH_LOGIN_FAILURE_RETENTION_MAX_ROWS", "5000")),
        gt=0,
    )
    operational_event_retention_days: int = Field(
        default=int(os.getenv("OPERATIONAL_EVENT_RETENTION_DAYS", "90")),
        gt=0,
    )
    operational_event_retention_max_rows: int = Field(
        default=int(os.getenv("OPERATIONAL_EVENT_RETENTION_MAX_ROWS", "50000")),
        gt=0,
    )
    operational_retention_batch_size: int = Field(
        default=int(os.getenv("OPERATIONAL_RETENTION_BATCH_SIZE", "500")),
        gt=0,
    )
    operational_retention_interval_seconds: int = Field(
        default=int(os.getenv("OPERATIONAL_RETENTION_INTERVAL_SECONDS", "21600")),
        gt=0,
    )
    disable_auth: bool = _parse_bool(os.getenv("MOBILE_API_DISABLE_AUTH", "0"))
    allow_public_auth_bypass: bool = _parse_bool(os.getenv("MOBILE_API_ALLOW_PUBLIC_AUTH_BYPASS", "0"))
    cors_origins: list[str] = _parse_cors_origins(
        os.getenv(
            "MOBILE_API_CORS_ORIGINS",
            "http://localhost,http://127.0.0.1,capacitor://localhost,https://novel-tnn.tradingcompanydirect.com",
        )
    )
    serve_web: bool = _parse_bool(os.getenv("MOBILE_API_SERVE_WEB", "1"))
    web_dist_dir: str = os.getenv("WEB_DIST_DIR", "web/dist")


mobile_settings = MobileAPISettings()


_DEV_SECRET_VALUES = {
    "",
    "dev-secret",
    "dev-secret-change-in-production",
    "change-this-jwt-secret",
    "change_me",
    "changeme",
}
_DEV_ADMIN_PASSWORD_VALUES = {
    "",
    "admin",
    "password",
    "password123",
    "change_me",
    "changeme",
    "dev-password",
}
_DEV_ADMIN_USERNAMES = {"", "admin", "administrator", "root"}


def _is_broad_public_cors_origin(origin: str) -> bool:
    value = origin.strip().lower()
    if not value:
        return False
    if value == "*" or "*" in value or value == "null":
        return True
    if value.startswith("http://"):
        return True
    return not value.startswith("https://")


def validate_public_deploy_settings(settings: MobileAPISettings | None = None) -> list[str]:
    """Return PUBLIC_DEPLOY safety violations for externally exposed instances."""
    resolved = settings or mobile_settings
    if not resolved.public_deploy:
        return []

    errors: list[str] = []
    secret = resolved.secret_key.strip()
    if secret.lower() in _DEV_SECRET_VALUES or len(secret) < 32:
        errors.append("MOBILE_API_SECRET must be a long random secret when PUBLIC_DEPLOY=1")

    username = resolved.admin_username.strip()
    if username.lower() in _DEV_ADMIN_USERNAMES:
        errors.append("MOBILE_API_ADMIN_USERNAME must be set to a non-default operator username")

    password = resolved.admin_password.strip()
    if password.lower() in _DEV_ADMIN_PASSWORD_VALUES or len(password) < 12:
        errors.append("MOBILE_API_ADMIN_PASSWORD must be a strong non-default password")

    broad_origins = [origin for origin in resolved.cors_origins if _is_broad_public_cors_origin(origin)]
    if broad_origins:
        errors.append(
            "MOBILE_API_CORS_ORIGINS must contain only exact https:// origins when PUBLIC_DEPLOY=1; "
            f"unsafe values: {', '.join(broad_origins)}"
        )
    if resolved.disable_auth and not resolved.allow_public_auth_bypass:
        errors.append(
            "MOBILE_API_DISABLE_AUTH cannot be enabled when PUBLIC_DEPLOY=1 "
            "unless MOBILE_API_ALLOW_PUBLIC_AUTH_BYPASS=1 is explicitly set"
        )

    return errors


def assert_public_deploy_safe(settings: MobileAPISettings | None = None) -> None:
    errors = validate_public_deploy_settings(settings)
    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"Unsafe PUBLIC_DEPLOY configuration: {joined}")


def auth_bypass_enabled(settings: MobileAPISettings | None = None) -> bool:
    resolved = settings or mobile_settings
    if not resolved.disable_auth:
        return False
    return not resolved.public_deploy or resolved.allow_public_auth_bypass
