from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import errno
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.config import PROJECT_ROOT
from app.database.db import find_managed_source_for_url, get_chapter_by_id, get_managed_source, list_ebook_import_runs
from app.database.import_jobs import (
    ImportJob,
    InvalidImportJobTransition,
    JobStatus as DurableImportJobStatus,
    TaskStatus as DurableImportTaskStatus,
)
from app.ingestion.source_adapters import FetchErrorCode, FetchMethod, SourceAdapterError, list_source_capabilities, validate_public_http_url
from app.ingestion.source_policies import chapter_url_matches_source_book, get_source_policy
from app.mobile_api.auth import get_current_user
from app.mobile_api.audit import record_audit_event
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.mobile_api.schemas import (
    JobResponse,
    ImportJobAcceptedResponse,
    ImportJobCreateRequest,
    ImportJobErrorResponse,
    ImportJobEventData,
    ImportJobSnapshotResponse,
    PasteImport,
    SourceCapabilityList,
    SourcePreviewResponse,
    URLFetchChapterResult,
    URLFetchRequest,
    URLFetchResponse,
    URLImportStart,
    URLNoteImport,
    URLPreviewRequest,
    WizardTextImport,
    WizardTextImportResult,
)
from app.mobile_api.services.ebook_import_service import EbookImportService, ExistingBookConfirmationRequired
from app.mobile_api.services.import_job_wait_service import ImportJobWaitError, wait_for_terminal_import_job
from app.mobile_api.services.job_service import get_shared_job_tracker
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.public_mode import is_public_request
from app.mobile_api.upload_limits import read_upload_bytes_limited, write_upload_to_temp_limited
from app.services.import_job_service import ImportJobService
from app.services.import_job_quotas import ImportJobQuotaError
from app.services.import_job_factory import create_import_job_service
from app.import_contracts import BrowserResultState, BrowserTaskResult, ImportOperationKind
from app.runtime_identity import get_runtime_identity
from app.runtime_status import WorkerRuntimeStatus, inspect_worker_runtime

router = APIRouter(prefix="/api/import", tags=["import"])
logger = logging.getLogger(__name__)
EBOOK_UPLOAD_TTL_SECONDS = 6 * 60 * 60
EBOOK_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")
SUPPORTED_EBOOK_SUFFIXES = {".epub", ".azw3", ".mobi", ".prc", ".txt", ".html", ".htm"}
MAX_WIZARD_TEXT_IMPORT_BYTES = 5 * 1024 * 1024
EBOOK_CONFIRMATION_REQUIRED_DETAIL = (
    "Truyện này đã tồn tại trong Library. Hãy Preview và xác nhận gộp vào truyện hiện có."
)
IMPORT_JOB_TERMINAL_STATUSES = {
    DurableImportJobStatus.SUCCEEDED,
    DurableImportJobStatus.PARTIALLY_SUCCEEDED,
    DurableImportJobStatus.FAILED,
    DurableImportJobStatus.CANCELLED,
}
IMPORT_JOB_SSE_POLL_SECONDS = 0.25
IMPORT_JOB_SSE_KEEPALIVE_SECONDS = 15.0
IMPORT_JOB_ERROR_RESPONSES = {
    400: {"model": ImportJobErrorResponse, "description": "Invalid import request"},
    404: {"model": ImportJobErrorResponse, "description": "Import job not found"},
    409: {"model": ImportJobErrorResponse, "description": "Import job state conflict"},
    422: {"model": ImportJobErrorResponse, "description": "Import request quota or validation failure"},
}
IMPORT_JOB_SSE_RESPONSES = {
    **IMPORT_JOB_ERROR_RESPONSES,
    200: {
        "description": "Persisted import job events",
        "content": {
            "text/event-stream": {
                "schema": ImportJobEventData.model_json_schema(),
            }
        },
    },
}


def _source_adapter_http_exception(exc: SourceAdapterError, *, default_status: int = 400) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status or default_status,
        detail=exc.safe_message,
        headers={
            "X-Novel-Fetch-Error-Code": exc.code.value,
            "X-Novel-Fetch-Retryable": "1" if exc.retryable else "0",
        },
    )


def get_pipeline():
    return PipelineService()


def get_import_job_service(
    pipeline: PipelineService = Depends(get_pipeline),
) -> ImportJobService:
    return create_import_job_service(
        worker_id=f"api-{os.getpid()}",
        pipeline=pipeline,
        db_path=Path(getattr(pipeline, "db_path", get_db_path())),
    )


def get_import_worker_runtime() -> WorkerRuntimeStatus:
    return inspect_worker_runtime(
        data_dir=get_data_dir(),
        db_path=get_db_path(),
        api_identity=get_runtime_identity(component="api"),
        required=True,
        max_age_seconds=mobile_settings.import_worker_heartbeat_max_age_seconds,
    )


def get_ebook_import_service():
    return EbookImportService()


def _import_job_owner(current_user: dict) -> str:
    owner = str(current_user.get("user_id") or current_user.get("username") or "").strip()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_owner", "retryable": False, "message": "Authenticated owner is unavailable"},
        )
    return owner


def _import_job_http_error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "retryable": False, "message": message},
    )


def _raise_import_job_error(exc: Exception) -> None:
    if isinstance(exc, ImportJobQuotaError):
        status_code = 422 if exc.code == "chapter_quota_exceeded" else 429
        raise _import_job_http_error(exc.code, exc.safe_message, status_code) from exc
    if isinstance(exc, (LookupError, PermissionError)):
        raise _import_job_http_error("job_not_found", "Import job not found", 404) from exc
    if isinstance(exc, InvalidImportJobTransition):
        raise _import_job_http_error("invalid_job_state", "Import job state does not allow this action", 409) from exc
    if isinstance(exc, SourceAdapterError):
        raise HTTPException(
            status_code=exc.http_status or 400,
            detail={"code": exc.code.value, "retryable": exc.retryable, "message": exc.safe_message},
        ) from exc
    raise exc


def _validated_import_job_selection(
    data: ImportJobCreateRequest | URLFetchRequest,
) -> tuple[str, str, list[dict[str, object]]]:
    if not data.title.strip():
        raise _import_job_http_error("invalid_request", "Book title is required", 422)
    if not data.chapters:
        raise _import_job_http_error("invalid_request", "At least one chapter must be selected", 422)
    if len(data.chapters) > mobile_settings.import_job_max_chapters:
        raise _import_job_http_error(
            "chapter_quota_exceeded",
            f"A job can include at most {mobile_settings.import_job_max_chapters} chapters",
            422,
        )

    source_url = validate_public_http_url(data.source_url or data.chapters[0].url)
    source_policy = get_source_policy(source_url)
    if source_policy is None:
        raise SourceAdapterError(
            "Unsupported source domain",
            code=FetchErrorCode.SOURCE_NOT_ALLOWED,
            retryable=False,
            http_status=400,
        )

    tasks: list[dict[str, object]] = []
    seen: set[str] = set()
    for chapter in data.chapters:
        chapter_url = validate_public_http_url(chapter.url)
        chapter_policy = get_source_policy(chapter_url)
        if chapter_policy is None or chapter_policy.source_id != source_policy.source_id:
            raise SourceAdapterError(
                "Selected chapters must belong to the same supported source",
                code=FetchErrorCode.SOURCE_NOT_ALLOWED,
                retryable=False,
                http_status=400,
            )
        if not chapter_url_matches_source_book(source_url, chapter_url):
            raise SourceAdapterError(
                "Selected chapters must belong to the same source book",
                code=FetchErrorCode.SOURCE_NOT_ALLOWED,
                retryable=False,
                http_status=400,
            )
        if chapter_url in seen:
            raise SourceAdapterError(
                "Duplicate chapter selection",
                code=FetchErrorCode.DUPLICATE,
                retryable=False,
                http_status=409,
            )
        seen.add(chapter_url)
        tasks.append(
            {
                "canonical_identity": f"{source_policy.source_id}:{chapter_url}",
                "canonical_chapter_url": chapter_url,
                "chapter_number": chapter.chapter_number,
                "title": chapter.title,
            }
        )
    return source_url, source_policy.source_id, tasks


def _create_durable_import_job(
    service: ImportJobService,
    data: ImportJobCreateRequest | URLFetchRequest,
    owner_user_id: str,
) -> ImportJob:
    source_url, source_id, tasks = _validated_import_job_selection(data)
    job = service.create_job(
        owner_user_id=owner_user_id,
        source=data.source.strip() or source_id,
        source_url=source_url,
        tasks=tasks,
        config_snapshot={
            "title": data.title.strip(),
            "author": data.author.strip(),
            "source": data.source.strip() or source_id,
            "source_url": source_url,
        },
    )
    return service.enqueue_job(job.id, owner_user_id)


def _create_durable_legacy_url_import_job(
    service: ImportJobService,
    data: URLImportStart,
    owner_user_id: str,
) -> ImportJob:
    source_url, chapters, retry_limit = _validated_url_import_payload(data)
    source_policy = get_source_policy(source_url)
    if source_policy is None:
        raise SourceAdapterError("Unsupported source domain")
    tasks = [
        {
            "canonical_identity": f"{source_policy.source_id}:{chapter['url']}",
            "canonical_chapter_url": chapter["url"],
            "chapter_number": chapter["chapter_number"],
            "title": chapter["title"],
        }
        for chapter in chapters
    ]
    source = data.source.strip() or source_policy.source_id
    job = service.create_job(
        owner_user_id=owner_user_id,
        source=source,
        source_url=source_url,
        tasks=tasks,
        config_snapshot={
            "title": data.title.strip(),
            "author": data.author.strip(),
            "source": source,
            "source_url": source_url,
            "managed_source_id": str(data.managed_source_id or "").strip(),
            "retry_limit": retry_limit,
            "legacy_url_retry_limit": retry_limit,
        },
        operation_kind=ImportOperationKind.IMPORT_CHAPTERS,
    )
    return service.enqueue_job(job.id, owner_user_id)


def _import_job_snapshot(
    service: ImportJobService,
    job_id: str,
    owner_user_id: str,
) -> dict:
    job = service.get_job(job_id, owner_user_id)
    tasks = service.list_tasks(job_id, owner_user_id)
    return {
        "job_id": job.id,
        "status": job.status.value,
        "source": job.source,
        "book_id": job.book_id,
        "total": job.total,
        "queued_count": job.queued_count,
        "running_count": job.running_count,
        "succeeded_count": job.succeeded_count,
        "failed_count": job.failed_count,
        "cancelled_count": job.cancelled_count,
        "waiting_retry_count": job.waiting_retry_count,
        "verification_required_count": job.verification_required_count,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "cancel_requested_at": job.cancel_requested_at,
        "error_summary": job.error_summary,
        "tasks": [
            {
                "id": task.id,
                "chapter_number": task.chapter_number,
                "title": task.title,
                "status": task.status.value,
                "stage": task.stage.value,
                "attempts": task.attempts,
                "next_attempt_at": task.next_attempt_at,
                "error_code": task.error_code,
                "error_message": task.error_message,
                "retryable": task.retryable,
                "fetch_method": task.fetch_method,
                "text_length": task.text_length,
                "content_hash": task.content_hash,
                "elapsed_ms": task.elapsed_ms,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
                "book_id": task.book_id,
                "chapter_id": task.chapter_id,
            }
            for task in tasks
        ],
    }


def _sse_event(event) -> str:
    payload = {
        "sequence": event.sequence,
        "job_id": event.job_id,
        "task_id": event.task_id,
        "type": event.event_type,
        "data": event.payload,
        "created_at": event.created_at,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: import_job_event\ndata: {data}\n\n"


async def _stream_import_job_events(
    request: Request,
    service: ImportJobService,
    job_id: str,
    owner_user_id: str,
    *,
    cursor: int,
):
    last_sequence = max(0, cursor)
    last_emit_at = time.monotonic()
    while True:
        if await request.is_disconnected():
            return
        events = await asyncio.to_thread(
            service.list_events,
            job_id,
            owner_user_id,
            after_sequence=last_sequence,
        )
        for event in events:
            last_sequence = event.sequence
            last_emit_at = time.monotonic()
            yield _sse_event(event)

        job = await asyncio.to_thread(service.get_job, job_id, owner_user_id)
        if job.status in IMPORT_JOB_TERMINAL_STATUSES:
            return
        if time.monotonic() - last_emit_at >= IMPORT_JOB_SSE_KEEPALIVE_SECONDS:
            last_emit_at = time.monotonic()
            yield ": keepalive\n\n"
        await asyncio.sleep(IMPORT_JOB_SSE_POLL_SECONDS)


@router.get("/sources", response_model=SourceCapabilityList)
async def list_sources():
    """Return the source domains and import policies currently enabled by the backend."""
    return {"sources": list_source_capabilities()}


def _import_error_status(error: ValueError) -> int:
    message = str(error)
    return 409 if "Duplicate chapter" in message else 400


def _url_fetch_error_metadata(exc: Exception) -> tuple[FetchErrorCode, bool, str, str]:
    if isinstance(exc, SourceAdapterError):
        method = (
            FetchMethod.USER_VERIFICATION_REQUIRED.value
            if exc.code is FetchErrorCode.USER_VERIFICATION_REQUIRED
            else ""
        )
        return exc.code, exc.retryable, exc.safe_message, method
    if isinstance(exc, ValueError) and "Duplicate" in str(exc):
        return FetchErrorCode.DUPLICATE, False, "Chapter already exists", ""
    return (
        FetchErrorCode.IMPORT_FAILED,
        False,
        "Chapter import failed. Check the source metadata and try again.",
        "",
    )


def _safe_import_response(result: dict, request: Request) -> dict:
    payload = dict(result)
    if is_public_request(request):
        payload["path"] = ""
    return payload


def _wizard_text_payload_bytes(data: WizardTextImport) -> int:
    total = 0
    for chapter in data.chapters:
        total += len(chapter.text.encode("utf-8"))
        total += len(chapter.raw_text.encode("utf-8"))
        total += len(chapter.translated_text.encode("utf-8"))
        total += len(chapter.chapter_title.encode("utf-8"))
    total += len(data.title.encode("utf-8"))
    total += len(data.author.encode("utf-8"))
    return total


def _validated_url_import_payload(data: URLImportStart) -> tuple[str, list[dict], int]:
    source_url = validate_public_http_url(data.url)
    source_policy = get_source_policy(source_url)
    if source_policy is None:
        raise SourceAdapterError("Unsupported source domain")

    chapters: list[dict] = []
    seen: set[str] = set()
    for chapter in data.chapters:
        chapter_data = chapter.model_dump()
        chapter_url = validate_public_http_url(chapter_data["url"])
        chapter_policy = get_source_policy(chapter_url)
        if chapter_policy is None or chapter_policy.source_id != source_policy.source_id:
            raise SourceAdapterError("Selected chapters must belong to the same supported source")
        if not chapter_url_matches_source_book(source_url, chapter_url):
            raise SourceAdapterError("Selected chapters must belong to the same source book")
        if chapter_url in seen:
            raise SourceAdapterError(
                "Duplicate chapter selection",
                code=FetchErrorCode.DUPLICATE,
                retryable=False,
                http_status=409,
            )
        seen.add(chapter_url)
        chapter_data["url"] = chapter_url
        chapters.append(chapter_data)

    return source_url, chapters, min(data.retry_limit, source_policy.retry_limit)


@router.post("/paste", response_model=dict)
async def import_paste(
    data: PasteImport,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    """Import from pasted text."""
    if not data.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    try:
        result = pipeline.import_from_text(
            title=data.title,
            chapter_number=data.chapter_number,
            chapter_title=data.chapter_title,
            text=data.text,
            source_type="paste",
        )
    except ValueError as exc:
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Paste import failed",
            request=request,
            details={"import_type": "paste", "result": "failure"},
        )
        raise HTTPException(status_code=_import_error_status(exc), detail=str(exc)) from exc
    record_audit_event(
        event_type="import_complete",
        severity="info",
        source="import",
        message="Paste import completed",
        request=request,
        details={
            "import_type": "paste",
            "result": "success",
            "book_id": result.get("book_id", 0),
            "chapter_id": result.get("chapter_id", 0),
        },
    )
    return {**_safe_import_response(result, request), "message": "Imported from paste"}


@router.post("/wizard/text", response_model=WizardTextImportResult)
async def import_wizard_text(
    data: WizardTextImport,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    """Commit a reviewed paste/TXT import plan from the guided wizard."""
    if _wizard_text_payload_bytes(data) > MAX_WIZARD_TEXT_IMPORT_BYTES:
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Wizard text import rejected because payload is too large",
            request=request,
            details={"import_type": "wizard_text", "result": "failure", "reason": "payload_too_large"},
        )
        raise HTTPException(
            status_code=413,
            detail=f"Import text payload is too large. Limit is {MAX_WIZARD_TEXT_IMPORT_BYTES // (1024 * 1024)} MB.",
        )
    try:
        result = await asyncio.to_thread(
            pipeline.import_reviewed_text_plan,
            title=data.title,
            author=data.author,
            target_book_id=data.target_book_id,
            content_kind=data.content_kind,
            duplicate_strategy=data.duplicate_strategy,
            source_type=data.source_type,
            chapters=[chapter.model_dump() for chapter in data.chapters],
        )
    except ValueError as exc:
        message = str(exc)
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Wizard text import failed",
            request=request,
            details={
                "import_type": "wizard_text",
                "result": "failure",
                "reason": "duplicate" if "Duplicate chapter" in message else "validation",
            },
        )
        raise HTTPException(status_code=_import_error_status(exc), detail=message) from exc
    except Exception:
        logger.exception("Wizard text import failed")
        record_audit_event(
            event_type="import_failure",
            severity="error",
            source="import",
            message="Wizard text import failed",
            request=request,
            details={"import_type": "wizard_text", "result": "failure"},
        )
        raise HTTPException(status_code=500, detail="Import failed. Check the import plan and server logs.") from None

    record_audit_event(
        event_type="import_complete",
        severity="info",
        source="import",
        message="Wizard text import completed",
        request=request,
        details={
            "import_type": "wizard_text",
            "result": "success",
            "book_id": result.get("book_id", 0),
            "chapter_count": result.get("chapter_count", 0),
            "imported_chapters": result.get("imported_chapters", 0),
            "skipped_chapters": result.get("skipped_chapters", 0),
            "overwritten_chapters": result.get("overwritten_chapters", 0),
        },
    )
    return {**result, "message": "Imported reviewed text"}


@router.post("/file", response_model=dict)
async def import_file(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    chapter_number: int = Form(1),
    chapter_title: str = Form(""),
    pipeline: PipelineService = Depends(get_pipeline),
):
    """Import from uploaded .txt file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    # Save uploaded file to temp location
    data_dir = pipeline.data_dir
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    original_name = Path(file.filename).name
    safe_name = pipeline._safe_filename_part(original_name) or "upload.txt"
    temp_path = raw_dir / f"upload_{time.time_ns()}_{safe_name}"

    content = await read_upload_bytes_limited(file, label="Raw text upload")
    temp_path.write_bytes(content)

    try:
        result = pipeline.import_from_file(
            title=title,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            file_path=temp_path,
            filename=original_name,
        )
    except ValueError as exc:
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="File import failed",
            request=request,
            details={"import_type": "file", "result": "failure"},
        )
        raise HTTPException(status_code=_import_error_status(exc), detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)
    record_audit_event(
        event_type="import_complete",
        severity="info",
        source="import",
        message="File import completed",
        request=request,
        details={
            "import_type": "file",
            "result": "success",
            "book_id": result.get("book_id", 0),
            "chapter_id": result.get("chapter_id", 0),
        },
    )
    return {**_safe_import_response(result, request), "message": "Imported from file"}


async def _uploaded_ebook_temp_path(file: UploadFile) -> tuple[Path, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    original_name = Path(file.filename).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_EBOOK_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported ebook format")
    temp_path = await write_upload_to_temp_limited(
        file,
        suffix=suffix,
        prefix="novel-ebook-",
        label="Ebook upload",
    )
    if temp_path.stat().st_size <= 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File is empty")
    return temp_path, original_name


def _ebook_upload_dir(service: EbookImportService) -> Path:
    upload_dir = service.data_dir / "import_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _cleanup_staged_ebook_uploads(service: EbookImportService) -> None:
    upload_dir = _ebook_upload_dir(service)
    cutoff = time.time() - EBOOK_UPLOAD_TTL_SECONDS
    for path in upload_dir.iterdir():
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _stage_ebook_upload(service: EbookImportService, temp_path: Path, original_name: str) -> str:
    _cleanup_staged_ebook_uploads(service)
    upload_id = uuid.uuid4().hex
    upload_dir = _ebook_upload_dir(service)
    staged_path = upload_dir / f"{upload_id}{temp_path.suffix.lower()}"
    try:
        os.replace(temp_path, staged_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # ``copy2`` preserves timestamps and permissions, which is rejected by
        # some production bind mounts. Staging only needs the ebook bytes.
        try:
            shutil.copyfile(temp_path, staged_path)
            temp_path.unlink()
        except Exception:
            staged_path.unlink(missing_ok=True)
            raise
    meta_path = upload_dir / f"{upload_id}.json"
    meta_path.write_text(json.dumps({"filename": original_name}, ensure_ascii=False), encoding="utf-8")
    return upload_id


def _resolve_staged_ebook_upload(service: EbookImportService, upload_id: str) -> tuple[Path, str]:
    if not EBOOK_UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=400, detail="Invalid ebook upload id")
    upload_dir = _ebook_upload_dir(service)
    meta_path = upload_dir / f"{upload_id}.json"
    if not meta_path.exists():
        raise HTTPException(status_code=400, detail="Preview upload expired; select the ebook file again")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Preview upload metadata is invalid") from exc
    original_name = Path(str(metadata.get("filename") or "translated.epub")).name
    suffix = Path(original_name).suffix.lower()
    staged_path = upload_dir / f"{upload_id}{suffix}"
    if not staged_path.exists():
        raise HTTPException(status_code=400, detail="Preview upload expired; select the ebook file again")
    return staged_path, original_name


def _delete_staged_ebook_upload(service: EbookImportService, upload_id: str) -> None:
    if not EBOOK_UPLOAD_ID_RE.match(upload_id):
        return
    upload_dir = _ebook_upload_dir(service)
    for path in upload_dir.glob(f"{upload_id}*"):
        path.unlink(missing_ok=True)


async def _run_translated_ebook_import_job(
    *,
    job_id: str,
    tracker,
    service: EbookImportService,
    ebook_path: Path,
    original_name: str,
    target_book_id: int | None,
    duplicate_strategy: str,
    split_mode: str,
    confirmed_existing_book_id: int | None,
    cleanup_upload_id: str = "",
    cleanup_temp_path: bool = False,
) -> None:
    tracker.update_job(job_id, status="running", progress=0, message="Importing translated ebook")
    confirmation_conflict = False
    try:
        result = await asyncio.to_thread(
            service.import_translated_ebook,
            ebook_path,
            target_book_id=target_book_id,
            duplicate_strategy=duplicate_strategy,
            split_mode=split_mode,
            original_filename=original_name,
            confirmed_existing_book_id=confirmed_existing_book_id,
        )
        imported = int(result.get("imported_chapters") or 0)
        skipped = int(result.get("skipped_chapters") or 0)
        job = tracker.get_job(job_id)
        params = dict(job.params or {}) if job else {}
        params.update(
            {
                "book_id": result.get("book_id", 0),
                "chapter_count": result.get("chapter_count", imported),
                "imported_chapters": imported,
                "skipped_chapters": skipped,
            }
        )
        tracker.update_job(
            job_id,
            status="completed",
            progress=1,
            message=f"Imported {imported} translated ebook chapter(s), skipped {skipped}.",
            params=params,
        )
        record_audit_event(
            event_type="import_complete",
            severity="info",
            source="import",
            message="Translated ebook import completed",
            job_id=job_id,
            details={
                "import_type": "ebook",
                "result": "success",
                "book_id": result.get("book_id", 0),
                "chapter_count": imported,
                "skipped_chapters": skipped,
            },
        )
    except ExistingBookConfirmationRequired:
        confirmation_conflict = True
        job = tracker.get_job(job_id)
        params = dict(job.params or {}) if job else {}
        params["confirmed_existing_book_id"] = None
        if cleanup_upload_id:
            params["retry_upload_id"] = cleanup_upload_id
        elif cleanup_temp_path:
            params["retry_upload_id"] = _stage_ebook_upload(service, ebook_path, original_name)
        else:
            params["retry_inbox_file"] = original_name
        logger.info("Translated ebook import job %s requires a fresh Preview and confirmation", job_id)
        tracker.update_job(
            job_id,
            status="failed",
            error=EBOOK_CONFIRMATION_REQUIRED_DETAIL,
            message=EBOOK_CONFIRMATION_REQUIRED_DETAIL,
            params=params,
        )
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Translated ebook import requires existing book confirmation",
            job_id=job_id,
            details={"import_type": "ebook", "result": "failure", "reason": "confirmation_required"},
        )
    except ValueError as exc:
        logger.info("Translated ebook import job %s failed: %s", job_id, exc)
        tracker.update_job(
            job_id,
            status="failed",
            error="Translated ebook import failed. Check duplicate settings, ebook file, and server logs.",
            message="Translated ebook import failed. Check duplicate settings, ebook file, and server logs.",
        )
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Translated ebook import failed",
            job_id=job_id,
            details={"import_type": "ebook", "result": "failure"},
        )
    except Exception:
        logger.exception("Translated ebook import job %s failed", job_id)
        tracker.update_job(
            job_id,
            status="failed",
            error="Translated ebook import failed. Check server logs.",
            message="Translated ebook import failed. Check server logs.",
        )
        record_audit_event(
            event_type="import_failure",
            severity="error",
            source="import",
            message="Translated ebook import failed",
            job_id=job_id,
            details={"import_type": "ebook", "result": "failure"},
        )
    finally:
        if not confirmation_conflict:
            if cleanup_upload_id:
                _delete_staged_ebook_upload(service, cleanup_upload_id)
            if cleanup_temp_path:
                ebook_path.unlink(missing_ok=True)


def _ebook_inbox_dir() -> Path:
    configured = os.getenv("EBOOK_INBOX_DIR", "inbox/ebooks")
    inbox_dir = Path(configured).expanduser()
    if not inbox_dir.is_absolute():
        inbox_dir = PROJECT_ROOT / inbox_dir
    inbox_dir.mkdir(parents=True, exist_ok=True)
    return inbox_dir


def _resolve_inbox_ebook(filename: str) -> tuple[Path, str]:
    original_name = Path(filename).name
    if not original_name or original_name != filename:
        raise HTTPException(status_code=400, detail="Invalid inbox ebook filename")
    if Path(original_name).suffix.lower() not in SUPPORTED_EBOOK_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported ebook format")

    inbox_dir = _ebook_inbox_dir().resolve()
    ebook_path = (inbox_dir / original_name).resolve()
    if inbox_dir not in ebook_path.parents:
        raise HTTPException(status_code=400, detail="Invalid inbox ebook filename")
    if not ebook_path.is_file():
        raise HTTPException(status_code=404, detail="Inbox ebook not found")
    return ebook_path, original_name


@router.get("/ebook/inbox", response_model=dict)
async def list_ebook_inbox():
    """List ebook files copied into the server-side inbox."""
    inbox_dir = _ebook_inbox_dir()
    files = []
    for path in sorted(inbox_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EBOOK_SUFFIXES:
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return {"directory": str(inbox_dir), "files": files}


@router.post("/ebook/inbox/preview", response_model=dict)
async def preview_inbox_translated_ebook(
    filename: str = Form(...),
    split_mode: str = Form(default="auto"),
    target_book_id: int | None = Form(default=None),
    duplicate_strategy: str = Form(default="skip"),
    service: EbookImportService = Depends(get_ebook_import_service),
):
    """Preview a translated ebook already present in the server-side inbox."""
    ebook_path, original_name = _resolve_inbox_ebook(filename)
    try:
        preview = service.preview(
            ebook_path,
            split_mode=split_mode,
            target_book_id=target_book_id,
            duplicate_strategy=duplicate_strategy,
            original_filename=original_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**preview, "inbox_file": original_name}


@router.post("/ebook/preview", response_model=dict)
async def preview_translated_ebook(
    file: UploadFile = File(...),
    split_mode: str = Form(default="auto"),
    target_book_id: int | None = Form(default=None),
    duplicate_strategy: str = Form(default="skip"),
    service: EbookImportService = Depends(get_ebook_import_service),
):
    """Preview a translated ebook before importing it into the Library."""
    temp_path, original_name = await _uploaded_ebook_temp_path(file)
    staged = False
    try:
        preview = service.preview(
            temp_path,
            split_mode=split_mode,
            target_book_id=target_book_id,
            duplicate_strategy=duplicate_strategy,
            original_filename=original_name,
        )
        upload_id = _stage_ebook_upload(service, temp_path, original_name)
        staged = True
        return {**preview, "upload_id": upload_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if not staged:
            temp_path.unlink(missing_ok=True)


@router.post("/ebook", response_model=dict)
async def import_translated_ebook(
    request: Request,
    file: UploadFile | None = File(default=None),
    upload_id: str | None = Form(default=None),
    inbox_file: str | None = Form(default=None),
    target_book_id: int | None = Form(default=None),
    duplicate_strategy: str = Form(default="skip"),
    split_mode: str = Form(default="auto"),
    confirmed_existing_book_id: int | None = Form(default=None),
    service: EbookImportService = Depends(get_ebook_import_service),
):
    """Import an already-translated ebook directly into the Library."""
    using_staged_upload = bool(upload_id)
    using_uploaded_file = False
    if upload_id:
        temp_path, original_name = _resolve_staged_ebook_upload(service, upload_id)
    elif inbox_file:
        temp_path, original_name = _resolve_inbox_ebook(inbox_file)
    elif file is not None:
        temp_path, original_name = await _uploaded_ebook_temp_path(file)
        using_uploaded_file = True
    else:
        raise HTTPException(status_code=400, detail="No file uploaded")
    confirmation_conflict = False
    try:
        result = service.import_translated_ebook(
            temp_path,
            target_book_id=target_book_id,
            duplicate_strategy=duplicate_strategy,
            split_mode=split_mode,
            original_filename=original_name,
            confirmed_existing_book_id=confirmed_existing_book_id,
        )
    except ExistingBookConfirmationRequired as exc:
        confirmation_conflict = True
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Translated ebook import requires existing book confirmation",
            request=request,
            details={"import_type": "ebook", "result": "failure", "reason": "confirmation_required"},
        )
        raise HTTPException(status_code=409, detail=EBOOK_CONFIRMATION_REQUIRED_DETAIL) from exc
    except ValueError as exc:
        message = str(exc)
        status = 409 if "Duplicate chapter" in message else 400
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Translated ebook import failed",
            request=request,
            details={"import_type": "ebook", "result": "failure"},
        )
        raise HTTPException(status_code=status, detail=message) from exc
    finally:
        if using_staged_upload and upload_id and not confirmation_conflict:
            _delete_staged_ebook_upload(service, upload_id)
        elif using_uploaded_file:
            temp_path.unlink(missing_ok=True)
    record_audit_event(
        event_type="import_complete",
        severity="info",
        source="import",
        message="Translated ebook import completed",
        request=request,
        details={
            "import_type": "ebook",
            "result": "success",
            "book_id": result.get("book_id", 0),
            "chapter_count": result.get("imported_chapters", result.get("chapter_count", 0)),
        },
    )
    return {**result, "message": "Imported translated ebook"}


@router.post("/ebook/job", response_model=JobResponse)
async def start_translated_ebook_import_job(
    request: Request,
    file: UploadFile | None = File(default=None),
    upload_id: str | None = Form(default=None),
    inbox_file: str | None = Form(default=None),
    target_book_id: int | None = Form(default=None),
    duplicate_strategy: str = Form(default="skip"),
    split_mode: str = Form(default="auto"),
    confirmed_existing_book_id: int | None = Form(default=None),
    service: EbookImportService = Depends(get_ebook_import_service),
):
    """Start a background import job for an already-translated ebook."""
    cleanup_upload_id = ""
    cleanup_temp_path = False
    source = "upload"
    if upload_id:
        ebook_path, original_name = _resolve_staged_ebook_upload(service, upload_id)
        cleanup_upload_id = upload_id
        source = "preview_upload"
    elif inbox_file:
        ebook_path, original_name = _resolve_inbox_ebook(inbox_file)
        source = "inbox"
    elif file is not None:
        ebook_path, original_name = await _uploaded_ebook_temp_path(file)
        cleanup_temp_path = True
    else:
        raise HTTPException(status_code=400, detail="No file uploaded")

    try:
        service.validate_existing_book_confirmation(
            ebook_path,
            target_book_id=target_book_id,
            split_mode=split_mode,
            original_filename=original_name,
            confirmed_existing_book_id=confirmed_existing_book_id,
        )
    except ExistingBookConfirmationRequired as exc:
        if cleanup_temp_path:
            ebook_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=EBOOK_CONFIRMATION_REQUIRED_DETAIL) from exc
    except ValueError as exc:
        if cleanup_temp_path:
            ebook_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tracker = get_shared_job_tracker(service.db_path)
    job = tracker.create_job(
        "import_ebook",
        [],
        1,
        {
            "source": source,
            "original_filename": original_name,
            "duplicate_strategy": duplicate_strategy,
            "split_mode": split_mode,
            "target_book_id": target_book_id,
            "confirmed_existing_book_id": confirmed_existing_book_id,
        },
    )
    tracker.start_background_task(
        job.job_id,
        _run_translated_ebook_import_job(
            job_id=job.job_id,
            tracker=tracker,
            service=service,
            ebook_path=ebook_path,
            original_name=original_name,
            target_book_id=target_book_id,
            duplicate_strategy=duplicate_strategy,
            split_mode=split_mode,
            confirmed_existing_book_id=confirmed_existing_book_id,
            cleanup_upload_id=cleanup_upload_id,
            cleanup_temp_path=cleanup_temp_path,
        ),
    )
    record_audit_event(
        event_type="import_start",
        severity="info",
        source="import",
        message="Translated ebook import job started",
        request=request,
        job_id=job.job_id,
        details={
            "import_type": "ebook",
            "result": "started",
            "source": source,
            "duplicate_strategy": duplicate_strategy,
            "split_mode": split_mode,
        },
    )
    return JobResponse(job_id=job.job_id, status="pending", message="Translated ebook import job started")


@router.get("/ebook/history", response_model=dict)
async def ebook_import_history(
    limit: int = 20,
    service: EbookImportService = Depends(get_ebook_import_service),
):
    """Return recent translated ebook import runs."""
    safe_limit = max(1, min(limit, 100))
    return {"runs": list_ebook_import_runs(service.db_path, limit=safe_limit)}


@router.post("/url-note", response_model=dict)
async def import_url_note(
    data: URLNoteImport,
    pipeline: PipelineService = Depends(get_pipeline),
):
    """Save URL note for manual handling."""
    book_id = pipeline.add_url_note(
        title=data.title or data.url,
        url=data.url,
        notes=data.notes,
        chapter_number=data.chapter_number,
        chapter_title=data.chapter_title,
    )
    return {"book_id": book_id, "message": "URL note saved"}


def _preview_http_exception(
    code: str,
    message: str,
    status_code: int,
    *,
    retryable: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "retryable": retryable, "message": message},
    )


def _stored_source_preview_error(
    result: BrowserTaskResult,
    *,
    default_status: int,
) -> HTTPException | None:
    try:
        error_code = FetchErrorCode(result.error_code)
    except ValueError:
        return None
    if error_code in {
        FetchErrorCode.CANCELLED,
        FetchErrorCode.IMPORT_FAILED,
        FetchErrorCode.INTERNAL_ERROR,
    }:
        return None
    error = SourceAdapterError(
        result.error_message or "Source preview failed",
        code=error_code,
        retryable=result.retryable,
        http_status=result.http_status,
    )
    return _source_adapter_http_exception(error, default_status=default_status)


def _source_preview_response(payload: dict, *, requested_url: str) -> SourcePreviewResponse:
    chapters = [dict(chapter) for chapter in payload.get("chapters") or []]
    preview = dict(payload)
    preview["chapters"] = chapters
    preview["chapter_count"] = len(chapters)
    managed = find_managed_source_for_url(
        get_db_path(),
        str(preview.get("source_url") or requested_url),
        str(preview.get("source") or ""),
        str((preview.get("policy") or {}).get("source_id") or ""),
    )
    preview["managed_source_id"] = str(managed.get("id") or "") if managed else ""
    preview["managed_source_status"] = str(managed.get("status") or "") if managed else ""
    preview["managed_source_trust_level"] = str(managed.get("trust_level") or "") if managed else ""
    preview["automation_allowed"] = bool(managed and managed.get("status") == "VERIFIED")
    preview["automation_reason"] = (
        ""
        if preview["automation_allowed"]
        else (
            "Nguồn này chưa được nhập vào Source Hub và xác minh."
            if managed is None
            else f"Nguồn đang ở trạng thái {managed.get('status', 'NEEDS_REVIEW')} nên chưa thể tạo job tự động."
        )
    )
    return SourcePreviewResponse.model_validate(preview)


@router.post("/url/preview", response_model=SourcePreviewResponse)
async def preview_source_url(
    data: URLPreviewRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
    worker_runtime: WorkerRuntimeStatus = Depends(get_import_worker_runtime),
):
    """Preview a public novel/book URL and extract candidate chapter links."""
    owner_user_id = _import_job_owner(current_user)
    try:
        source_url = validate_public_http_url(data.url)
        source_policy = get_source_policy(source_url)
        if source_policy is None:
            raise SourceAdapterError(
                "Unsupported source domain",
                code=FetchErrorCode.SOURCE_NOT_ALLOWED,
                retryable=False,
                http_status=400,
            )
        if not worker_runtime.queue_claim_capable:
            raise _preview_http_exception(
                "worker_unavailable",
                "Import worker is unavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                retryable=True,
            )

        correlation_id = str(uuid.uuid4())
        deadline_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=mobile_settings.import_preview_wait_timeout_seconds)
        ).isoformat()
        job = await asyncio.to_thread(
            service.create_job,
            owner_user_id=owner_user_id,
            source=source_policy.source_id,
            source_url=source_url,
            tasks=[
                {
                    "canonical_identity": f"{source_policy.source_id}:{source_url}",
                    "canonical_chapter_url": source_url,
                    "chapter_number": 0,
                    "title": "",
                }
            ],
            config_snapshot={"source": source_policy.source_id},
            operation_kind=ImportOperationKind.PREVIEW,
            deadline_at=deadline_at,
            correlation_id=correlation_id,
        )
        job = await asyncio.to_thread(service.enqueue_job, job.id, owner_user_id)
        job = await wait_for_terminal_import_job(
            request,
            service,
            job.id,
            owner_user_id,
            timeout_seconds=mobile_settings.import_preview_wait_timeout_seconds,
            poll_seconds=mobile_settings.import_job_wait_poll_seconds,
        )
        result = job.result_snapshot
        if result is None or job.result_state is not result.state:
            raise _preview_http_exception(
                "browser_task_failed",
                "Browser task failed",
                status.HTTP_502_BAD_GATEWAY,
            )
        if result.state is BrowserResultState.COMPLETED:
            if result.payload is None:
                raise _preview_http_exception(
                    "browser_task_failed",
                    "Browser task failed",
                    status.HTTP_502_BAD_GATEWAY,
                )
            return _source_preview_response(
                result.payload.model_dump(mode="python"),
                requested_url=source_url,
            )
        if result.state is BrowserResultState.BLOCKED:
            stored_error = _stored_source_preview_error(result, default_status=400)
            if stored_error is not None:
                raise stored_error
        elif result.state is BrowserResultState.FAILED:
            stored_error = _stored_source_preview_error(result, default_status=502)
            if stored_error is not None:
                raise stored_error
        elif result.state is BrowserResultState.TIMED_OUT:
            raise _preview_http_exception(
                "browser_task_timed_out",
                "Browser task deadline exceeded",
                status.HTTP_504_GATEWAY_TIMEOUT,
            )
        elif result.state is BrowserResultState.CANCELLED:
            raise _preview_http_exception(
                "browser_task_cancelled",
                "Browser task was cancelled",
                status.HTTP_409_CONFLICT,
            )
        raise _preview_http_exception(
            "browser_task_failed",
            "Browser task failed",
            status.HTTP_502_BAD_GATEWAY,
        )
    except ImportJobWaitError as exc:
        if exc.code == "client_disconnected":
            raise _preview_http_exception(
                "client_disconnected",
                "Client disconnected",
                499,
            ) from exc
        raise _preview_http_exception(
            "browser_task_timed_out",
            "Browser task deadline exceeded",
            status.HTTP_504_GATEWAY_TIMEOUT,
        ) from exc
    except SourceAdapterError as exc:
        raise _source_adapter_http_exception(exc) from exc
    except HTTPException:
        raise
    except (ImportJobQuotaError, InvalidImportJobTransition, LookupError, PermissionError) as exc:
        _raise_import_job_error(exc)
        raise
    except Exception as exc:
        logger.warning("Source preview failed in external worker")
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="Source preview failed",
            request=request,
            details={"import_type": "url_preview", "result": "failure"},
        )
        raise _preview_http_exception(
            "browser_task_failed",
            "Browser task failed",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc


@router.post("/url", response_model=JobResponse)
async def import_source_url(
    data: URLImportStart,
    request: Request,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    """Start a background import job for selected URL chapters."""
    owner_user_id = _import_job_owner(current_user)
    if not data.title.strip():
        raise HTTPException(status_code=400, detail="Book title is required")
    if not data.chapters:
        raise HTTPException(status_code=400, detail="At least one chapter must be selected")

    try:
        managed_source_id = str(data.managed_source_id or "").strip()
        if not managed_source_id:
            raise SourceAdapterError("Only VERIFIED sources can start automated URL import jobs")
        managed_source = get_managed_source(get_db_path(), managed_source_id)
        if managed_source is None:
            raise SourceAdapterError("Managed source not found")
        if str(managed_source.get("status") or "").upper() != "VERIFIED":
            raise SourceAdapterError("Only VERIFIED sources can start automated URL import jobs")
        source_url, chapters, retry_limit = _validated_url_import_payload(data)
        if source_url != str(managed_source.get("base_url") or ""):
            raise SourceAdapterError("Managed source URL does not match the selected preview URL")
        job = _create_durable_legacy_url_import_job(service, data, owner_user_id)
    except (SourceAdapterError, ImportJobQuotaError) as exc:
        record_audit_event(
            event_type="import_failure",
            severity="warning",
            source="import",
            message="URL import start failed",
            request=request,
            details={"import_type": "url", "result": "failure"},
        )
        if isinstance(exc, SourceAdapterError):
            raise _source_adapter_http_exception(exc) from exc
        _raise_import_job_error(exc)
        raise AssertionError("unreachable")
    record_audit_event(
        event_type="import_start",
        severity="info",
        source="import",
        message="URL import job started",
        request=request,
        job_id=job.id,
        details={
            "import_type": "url",
            "result": "started",
            "chapter_count": len(chapters),
            "retry_limit": retry_limit,
            "source": data.source,
        },
    )
    return JobResponse(job_id=job.id, status="pending", message="URL import job started")


@router.post(
    "/jobs",
    response_model=ImportJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=IMPORT_JOB_ERROR_RESPONSES,
)
async def create_import_job(
    data: ImportJobCreateRequest,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    """Create and enqueue a durable URL import job."""
    owner_user_id = _import_job_owner(current_user)
    try:
        job = _create_durable_import_job(service, data, owner_user_id)
    except Exception as exc:
        _raise_import_job_error(exc)
        raise
    return ImportJobAcceptedResponse(job_id=job.id, status=job.status.value, total=job.total)


@router.get(
    "/jobs/{job_id}",
    response_model=ImportJobSnapshotResponse,
    responses=IMPORT_JOB_ERROR_RESPONSES,
)
async def get_import_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    owner_user_id = _import_job_owner(current_user)
    try:
        return _import_job_snapshot(service, job_id, owner_user_id)
    except Exception as exc:
        _raise_import_job_error(exc)
        raise


@router.get(
    "/jobs/{job_id}/events",
    response_class=StreamingResponse,
    responses=IMPORT_JOB_SSE_RESPONSES,
)
async def stream_import_job_events(
    job_id: str,
    request: Request,
    cursor: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    owner_user_id = _import_job_owner(current_user)
    try:
        service.get_job(job_id, owner_user_id)
    except Exception as exc:
        _raise_import_job_error(exc)
        raise
    header_cursor = 0
    if last_event_id:
        try:
            header_cursor = max(0, int(last_event_id))
        except ValueError as exc:
            raise _import_job_http_error("invalid_cursor", "Last-Event-ID must be an integer", 400) from exc
    resolved_cursor = max(cursor, header_cursor)
    return StreamingResponse(
        _stream_import_job_events(
            request,
            service,
            job_id,
            owner_user_id,
            cursor=resolved_cursor,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ImportJobSnapshotResponse,
    responses=IMPORT_JOB_ERROR_RESPONSES,
)
async def cancel_import_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    owner_user_id = _import_job_owner(current_user)
    try:
        service.request_cancel(job_id, owner_user_id)
        return _import_job_snapshot(service, job_id, owner_user_id)
    except Exception as exc:
        _raise_import_job_error(exc)
        raise


@router.post(
    "/jobs/{job_id}/retry-failed",
    response_model=ImportJobSnapshotResponse,
    responses=IMPORT_JOB_ERROR_RESPONSES,
)
async def retry_failed_import_job_tasks(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
):
    owner_user_id = _import_job_owner(current_user)
    try:
        service.retry_failed_tasks(job_id, owner_user_id)
        snapshot = _import_job_snapshot(service, job_id, owner_user_id)
    except Exception as exc:
        _raise_import_job_error(exc)
        raise
    return snapshot


@router.post("/url/fetch", response_model=URLFetchResponse)
async def fetch_source_chapters(
    data: URLFetchRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    service: ImportJobService = Depends(get_import_job_service),
    worker_runtime: WorkerRuntimeStatus = Depends(get_import_worker_runtime),
):
    """Compatibility response backed by the same durable P09 job engine."""
    owner_user_id = _import_job_owner(current_user)
    try:
        source_url, source_id, tasks = _validated_import_job_selection(data)
        if not worker_runtime.queue_claim_capable:
            raise _import_job_http_error(
                "worker_unavailable",
                "Import worker is unavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        job = service.create_job(
            owner_user_id=owner_user_id,
            source=data.source.strip() or source_id,
            source_url=source_url,
            tasks=tasks,
            config_snapshot={
                "title": data.title.strip(),
                "author": data.author.strip(),
                "source": data.source.strip() or source_id,
                "source_url": source_url,
            },
        )
        job = service.enqueue_job(job.id, owner_user_id)
        await wait_for_terminal_import_job(
            request,
            service,
            job.id,
            owner_user_id,
            timeout_seconds=mobile_settings.import_job_sync_wait_timeout_seconds,
            poll_seconds=mobile_settings.import_job_wait_poll_seconds,
        )
        tasks = service.list_tasks(job.id, owner_user_id)
    except ImportJobWaitError as exc:
        if exc.code == "client_disconnected":
            raise _import_job_http_error("client_disconnected", "Client disconnected", 499) from exc
        raise _import_job_http_error(
            "import_job_timed_out",
            "Import job timed out",
            status.HTTP_504_GATEWAY_TIMEOUT,
        ) from exc
    except Exception as exc:
        _raise_import_job_error(exc)
        raise

    original_by_number = {chapter.chapter_number: chapter for chapter in data.chapters}
    results: list[URLFetchChapterResult] = []
    book_id = 0
    for task in tasks:
        original = original_by_number.get(task.chapter_number)
        succeeded_task = task.status is DurableImportTaskStatus.SUCCEEDED
        operation = "created" if succeeded_task else "failed"
        error_code = task.error_code
        if not succeeded_task and error_code == FetchErrorCode.INTERNAL_ERROR.value:
            error_code = FetchErrorCode.IMPORT_FAILED.value
        warnings: list[str] = []
        if task.chapter_id:
            stored = get_chapter_by_id(service.repository.db_path, task.chapter_id)
            if stored:
                operation = str(stored.get("last_import_operation") or operation)
        if succeeded_task and task.book_id:
            book_id = task.book_id
        results.append(
            URLFetchChapterResult(
                chapter_number=task.chapter_number,
                title=task.title,
                url=original.url if original is not None else "",
                success=succeeded_task,
                error="" if succeeded_task else task.error_message,
                text_length=task.text_length,
                book_id=task.book_id or 0,
                chapter_id=task.chapter_id or 0,
                stored_text_length=task.text_length,
                content_hash=task.content_hash,
                operation=operation,
                warnings=warnings,
                error_code=error_code,
                retryable=task.retryable,
                attempts=task.attempts,
                fetch_method=task.fetch_method,
                elapsed_ms=task.elapsed_ms,
                started_at=task.started_at,
                finished_at=task.finished_at,
            )
        )
    succeeded = sum(int(item.success) for item in results)
    failed = len(results) - succeeded

    record_audit_event(
        event_type="import_url_fetch",
        severity="info" if failed == 0 else "warning",
        source="import",
        message=f"URL fetch: {succeeded}/{len(data.chapters)} chapters imported",
        request=request,
        details={
            "import_type": "url_fetch",
            "title": data.title,
            "total": len(data.chapters),
            "succeeded": succeeded,
            "failed": failed,
        },
    )

    return URLFetchResponse(
        title=data.title,
        book_id=book_id,
        total=len(data.chapters),
        succeeded=succeeded,
        failed=failed,
        chapters=results,
    )
