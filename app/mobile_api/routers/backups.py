from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.mobile_api.audit import record_audit_event
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.schemas import JobResponse, SystemBackupItem, SystemBackupListResponse, SystemBackupRequest
from app.mobile_api.services.backup_job_service import BackupJobCoordinator
from app.mobile_api.services.backup_service import BackupService
from app.mobile_api.services.job_service import get_shared_job_tracker

router = APIRouter(prefix="/api/system/backups", tags=["backups"])
_SHARED_BACKUP_JOB_COORDINATOR: BackupJobCoordinator | None = None


def get_backup_job_coordinator() -> BackupJobCoordinator:
    global _SHARED_BACKUP_JOB_COORDINATOR
    tracker = get_shared_job_tracker(get_db_path())
    service = BackupService()
    if (
        _SHARED_BACKUP_JOB_COORDINATOR is None
        or _SHARED_BACKUP_JOB_COORDINATOR.tracker is not tracker
        or _SHARED_BACKUP_JOB_COORDINATOR.backup_service.backup_dir != service.backup_dir
    ):
        _SHARED_BACKUP_JOB_COORDINATOR = BackupJobCoordinator(
            tracker=tracker,
            backup_service=service,
        )
    return _SHARED_BACKUP_JOB_COORDINATOR


def get_backup_service() -> BackupService:
    return BackupService()


@router.get("", response_model=SystemBackupListResponse)
async def list_system_backups(service: BackupService = Depends(get_backup_service)):
    return SystemBackupListResponse(items=[SystemBackupItem(**item) for item in service.list_backups()])


@router.post("", response_model=JobResponse, status_code=202)
async def create_system_backup(
    payload: SystemBackupRequest,
    request: Request,
    coordinator: BackupJobCoordinator = Depends(get_backup_job_coordinator),
):
    try:
        payload.validate_for_queue()
        job_id = coordinator.start_backup_job(
            include_audio=payload.include_audio,
            include_exports=payload.include_exports,
            include_job_logs=payload.include_job_logs,
            include_secrets=payload.include_secrets,
            passphrase=payload.passphrase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_audit_event(
        event_type="backup_job_queued",
        severity="info",
        source="backups",
        message="Backup job queued",
        request=request,
        job_id=job_id,
        details={"result": "queued"},
    )
    return JobResponse(job_id=job_id, status="queued", message="Backup queued")


@router.get("/{filename}/download")
async def download_system_backup(
    filename: str,
    request: Request,
    service: BackupService = Depends(get_backup_service),
):
    try:
        path = service.resolve_download_path(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    record_audit_event(
        event_type="backup_download",
        severity="info",
        source="backups",
        message="System backup downloaded",
        request=request,
        details={"backup_name": path.name, "result": "success"},
    )
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)
