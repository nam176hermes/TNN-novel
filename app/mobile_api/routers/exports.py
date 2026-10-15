from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.mobile_api.audit import record_audit_event
from app.export.m4b_exporter import IncompleteAudiobookError
from app.mobile_api.schemas import ExportRequest, ExportResponse
from app.mobile_api.services.export_service import ExportService
from app.mobile_api.services.pipeline_service import PipelineService

router = APIRouter(prefix="/api/books/{book_id}/exports", tags=["exports"])


def get_export_service():
    return ExportService(PipelineService())


def _export_or_404(book_id: int, format: str, service: ExportService) -> dict:
    try:
        return service.export_book(book_id, format)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _safe_export_response(result: dict, _request: Request) -> dict:
    payload = dict(result)
    payload["path"] = ""
    return payload


def _annotation_export_or_404(book_id: int, format: str, service: ExportService, *, kind: str | None = None) -> dict:
    try:
        return service.export_annotations(book_id, format, kind=kind)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _audiobook_export_or_404(book_id: int, format: str, service: ExportService, allow_partial=False) -> dict:
    try:
        return service.export_audiobook(book_id, format, **({"allow_partial": True} if allow_partial else {}))
    except IncompleteAudiobookError as exc:
        raise HTTPException(status_code=409, detail={"code": "incomplete_audiobook",
            "message": "Một số chương chưa có audio hoặc audio đã cũ.", "missing_chapter_ids": exc.chapter_ids}) from exc
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("", response_model=ExportResponse)
def export_book(
    book_id: int,
    request: ExportRequest,
    http_request: Request,
    service: ExportService = Depends(get_export_service),
):
    """Create an export file for a translated book."""
    result = _export_or_404(book_id, request.format, service)
    record_audit_event(
        event_type="export_create",
        severity="info",
        source="exports",
        message="Book export created",
        request=http_request,
        details={"book_id": book_id, "format": request.format, "resource_type": "book_export", "result": "success"},
    )
    payload = _safe_export_response(result, http_request)
    payload["download_url"] = f"/api/books/{book_id}/exports/{request.format}/download"
    return payload


@router.get("/audiobook/{format}/download")
async def download_audiobook_export(
    book_id: int,
    format: str,
    request: Request,
    allow_partial: bool = Query(False),
    service: ExportService = Depends(get_export_service),
):
    """Create and download an audiobook export for a book with chapter audio."""
    result = await asyncio.to_thread(_audiobook_export_or_404, book_id, format, service, allow_partial)
    path = Path(result["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    record_audit_event(
        event_type="export_download",
        severity="info",
        source="exports",
        message="Audiobook export downloaded",
        request=request,
        details={"book_id": book_id, "format": format, "resource_type": "audiobook_export", "result": "success"},
    )
    return FileResponse(
        path,
        media_type=result["media_type"],
        filename=result["filename"],
    )


@router.get("/{format}/download")
def download_book_export(
    book_id: int,
    format: str,
    request: Request,
    service: ExportService = Depends(get_export_service),
):
    """Create and download an export file for a translated book."""
    result = _export_or_404(book_id, format, service)
    path = Path(result["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    record_audit_event(
        event_type="export_download",
        severity="info",
        source="exports",
        message="Book export downloaded",
        request=request,
        details={"book_id": book_id, "format": format, "resource_type": "book_export", "result": "success"},
    )
    return FileResponse(
        path,
        media_type=result["media_type"],
        filename=result["filename"],
    )


@router.get("/annotations/{format}/download")
def download_annotation_export(
    book_id: int,
    format: str,
    request: Request,
    kind: str | None = Query(None, description="Optional comma-separated annotation kind filter."),
    service: ExportService = Depends(get_export_service),
):
    """Create and download active reader annotations for a translated book."""
    result = _annotation_export_or_404(book_id, format, service, kind=kind)
    path = Path(result["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")
    record_audit_event(
        event_type="export_download",
        severity="info",
        source="exports",
        message="Annotation export downloaded",
        request=request,
        details={
            "book_id": book_id,
            "format": format,
            "kind": kind or "",
            "resource_type": "annotation_export",
            "result": "success",
        },
    )
    return FileResponse(
        path,
        media_type=result["media_type"],
        filename=result["filename"],
    )
