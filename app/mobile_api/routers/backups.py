from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.mobile_api.audit import record_audit_event
from app.mobile_api.schemas import SystemBackupItem, SystemBackupListResponse, SystemBackupRequest
from app.mobile_api.services.backup_service import BackupService

router = APIRouter(prefix="/api/system/backups", tags=["backups"])


def get_backup_service() -> BackupService:
    return BackupService()


@router.get("", response_model=SystemBackupListResponse)
async def list_system_backups(service: BackupService = Depends(get_backup_service)):
    return SystemBackupListResponse(items=[SystemBackupItem(**item) for item in service.list_backups()])


@router.post("", response_model=SystemBackupItem)
async def create_system_backup(
    payload: SystemBackupRequest,
    request: Request,
    service: BackupService = Depends(get_backup_service),
):
    try:
        item = service.create_backup(
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
        event_type="backup_create",
        severity="info",
        source="backups",
        message="System backup created",
        request=request,
        details={
            "backup_name": item["filename"],
            "encrypted": item["encrypted"],
            "secrets_included": item["secrets_included"],
            "result": "success",
        },
    )
    return SystemBackupItem(**item)


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
