from __future__ import annotations

import shutil
import os
import sqlite3
from pathlib import Path
import threading
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.database.db import count_mobile_jobs_by_status, list_operational_events
from app.mobile_api.config import auth_bypass_enabled, mobile_settings, validate_public_deploy_settings
from app.mobile_api.public_mode import is_public_request, sanitize_public_payload
from app.mobile_api.schemas import HealthResponse, ReadinessResponse, SystemStatusResponse, VersionResponse
from app.mobile_api.dependencies import get_db_path, get_data_dir
from app.mobile_api.services.retention_service import RetentionService

router = APIRouter(prefix="/api", tags=["health"])

_DATA_SIZE_CACHE_TTL_SECONDS = 60.0
_data_size_cache: dict[Path, tuple[int, float]] = {}
_data_size_refreshing: set[Path] = set()
_data_size_cache_lock = threading.Lock()


def _directory_size_bytes(root) -> int:
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _refresh_data_size_snapshot(root: Path) -> None:
    size_bytes = _directory_size_bytes(root)
    with _data_size_cache_lock:
        _data_size_cache[root] = (size_bytes, time.monotonic())
        _data_size_refreshing.discard(root)


def _cached_directory_size_bytes(root: Path, *, minimum_bytes: int = 0) -> int:
    resolved_root = root.resolve(strict=False)
    now = time.monotonic()
    refresh_thread: threading.Thread | None = None
    with _data_size_cache_lock:
        cached = _data_size_cache.get(resolved_root)
        if cached is None or now - cached[1] > _DATA_SIZE_CACHE_TTL_SECONDS:
            if resolved_root not in _data_size_refreshing:
                _data_size_refreshing.add(resolved_root)
                refresh_thread = threading.Thread(
                    target=_refresh_data_size_snapshot,
                    args=(resolved_root,),
                    daemon=True,
                    name="novel-data-size-snapshot",
                )
        cached_size = cached[0] if cached is not None else 0
    if refresh_thread is not None:
        refresh_thread.start()
    return max(cached_size, minimum_bytes)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", version=mobile_settings.version)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(request: Request, response: Response):
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}
    public_details: dict[str, str] = {}
    public_request = is_public_request(request)

    try:
        data_dir = get_data_dir()
        storage_ready = data_dir.exists() and os.access(data_dir, os.W_OK)
        checks["storage"] = storage_ready
        checks["data_dir_writable"] = storage_ready
        details["data_dir"] = str(data_dir)
        public_details["storage"] = "reachable" if storage_ready else "not reachable"
    except Exception as exc:
        checks["storage"] = False
        checks["data_dir_writable"] = False
        details["data_dir"] = str(exc)
        public_details["storage"] = "not reachable"
        data_dir = settings.resolved_data_dir

    try:
        db_path = get_db_path()
        if not db_path.exists():
            checks["database"] = False
            details["database"] = f"missing: {db_path}"
            public_details["database"] = "not reachable"
        else:
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("SELECT 1").fetchone()
            checks["database"] = True
            details["database"] = str(db_path)
            public_details["database"] = "reachable"
    except Exception as exc:
        checks["database"] = False
        details["database"] = str(exc)
        public_details["database"] = "not reachable"

    try:
        usage = shutil.disk_usage(data_dir)
        checks["disk_space"] = usage.free > 100 * 1024 * 1024
        details["disk_free_bytes"] = str(usage.free)
        public_details["disk_space"] = "sufficient" if checks["disk_space"] else "low"
    except Exception as exc:
        checks["disk_space"] = False
        details["disk_free_bytes"] = str(exc)
        public_details["disk_space"] = "unknown"

    try:
        count_mobile_jobs_by_status(get_db_path())
        checks["jobs"] = True
        public_details["jobs"] = "reachable"
    except Exception as exc:
        checks["jobs"] = False
        details["jobs"] = str(exc)
        public_details["jobs"] = "not reachable"

    if public_request:
        checks["public_deploy"] = mobile_settings.public_deploy
        public_details["public_deploy"] = "enabled" if mobile_settings.public_deploy else "disabled"
        public_config_errors = validate_public_deploy_settings()
        checks["public_config"] = mobile_settings.public_deploy and not public_config_errors
        public_details["public_config"] = "safe" if checks["public_config"] else "unsafe"
    else:
        checks["public_deploy"] = True
        public_details["public_deploy"] = "enabled" if mobile_settings.public_deploy else "disabled"

    status = "ok" if all(checks.values()) else "degraded"
    if status != "ok":
        response.status_code = 503
    return ReadinessResponse(
        status=status,
        checks=checks,
        details=public_details if (public_request or mobile_settings.public_deploy) else details,
    )


@router.get("/version", response_model=VersionResponse)
async def version_info():
    return VersionResponse(version=mobile_settings.version, build="phase1")


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(request: Request):
    from app.translation.cache import get_cache_stats
    from app.mobile_api.routers.jobs import get_shared_job_tracker
    from app.mobile_api.services.provider_service import ProviderService

    db_path = get_db_path()
    data_dir = get_data_dir()
    public_request = is_public_request(request)

    # DB size
    db_size = db_path.stat().st_size if db_path.exists() else 0

    # Cache stats
    try:
        cache = get_cache_stats(db_path)
    except Exception:
        cache = {"count": 0, "total_bytes": 0}

    jobs = get_shared_job_tracker().list_jobs(limit=100)
    running_jobs = [
        job for job in jobs
        if job.status.lower() in {"queued", "pending", "retrying", "running"}
    ]
    failed_jobs = [job for job in jobs if job.status.lower() in {"failed", "interrupted"}]
    last_failed = failed_jobs[0].to_dict() if failed_jobs else None
    job_counts = count_mobile_jobs_by_status(db_path)
    recent_operational_errors = list_operational_events(db_path, limit=10)
    recent_events = list_operational_events(db_path, limit=50, severities=())
    last_failed = sanitize_public_payload(last_failed)
    recent_operational_errors = sanitize_public_payload(recent_operational_errors)
    recent_events = sanitize_public_payload(recent_events)
    recent_backup_events = [
        event for event in recent_events
        if str(event.get("event_type") or "").startswith("backup_")
    ][:5]
    retention_service = getattr(request.app.state, "retention_service", None)
    if retention_service is None:
        retention_service = RetentionService(db_path, settings=mobile_settings)
    retention_status = await retention_service.get_status(db_path=db_path)

    active_provider = ""
    for job in running_jobs:
        provider_id = str((job.params or {}).get("provider_id") or "").strip()
        if provider_id:
            active_provider = provider_id
            break
    if not active_provider:
        try:
            active_provider = ProviderService().get_defaults().get("translate", "")
        except Exception:
            active_provider = ""

    api_ready = data_dir.exists() and db_path.exists()
    data_directory_available = data_dir.is_dir()
    database_available = db_path.is_file()
    database_inside_data_dir = False
    try:
        db_path.resolve().relative_to(data_dir.resolve())
        database_inside_data_dir = True
    except ValueError:
        pass
    data_size_bytes = (
        _cached_directory_size_bytes(
            data_dir,
            minimum_bytes=db_size if database_inside_data_dir else 0,
        )
        if data_directory_available
        else 0
    )
    if not database_inside_data_dir:
        data_size_bytes += db_size
    storage_health = "healthy" if api_ready else "degraded"

    return SystemStatusResponse(
        db_size_bytes=db_size,
        cache_count=cache.get("count", 0),
        cache_size_bytes=cache.get("total_bytes", 0),
        data_size_bytes=data_size_bytes,
        ollama_host="" if public_request else settings.ollama_host,
        ollama_model="" if public_request else settings.ollama_model,
        database_available=database_available,
        data_directory_available=data_directory_available,
        storage_health=storage_health,
        storage_label="Configured data storage",
        public_deploy=mobile_settings.public_deploy,
        api_ready=api_ready,
        active_provider=active_provider,
        upload_max_bytes=mobile_settings.upload_max_bytes,
        asset_protection_enabled=not auth_bypass_enabled(),
        active_jobs=len(running_jobs),
        running_jobs=sum(1 for job in running_jobs if job.status.lower() == "running"),
        queued_jobs=job_counts.get("queued", 0) + job_counts.get("pending", 0),
        retrying_jobs=job_counts.get("retrying", 0),
        interrupted_jobs=job_counts.get("interrupted", 0),
        failed_jobs=job_counts.get("failed", 0),
        last_failed_job=last_failed,
        recent_operational_errors=recent_operational_errors,
        recent_operational_events=recent_events[:20],
        recent_backup_events=recent_backup_events,
        retention=retention_status,
        app_version=mobile_settings.version,
        build="phase1",
        backup_recommendation="System backup is separate from book export. Run scripts/backup-local.sh before upgrades or public deploy changes.",
    )
