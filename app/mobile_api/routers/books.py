from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.mobile_api.auth import get_current_user
from app.mobile_api.audit import record_audit_event
from app.mobile_api.schemas import (
    BookCreate,
    BookUpdate,
    ParagraphPolishRequest,
    ReaderAnnotationCreate,
    ReaderAnnotationImportRequest,
    ReaderAnnotationUpdate,
    ReaderExplainRequest,
    ReaderExplainResponse,
    ReaderProgressUpdate,
    ReaderSyncRequest,
    ReaderXrayEnrichRequest,
    TranslationEdit,
    UserResponse,
)
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.upload_limits import read_upload_bytes_limited
from app.storage.artifact_paths import ArtifactPathError, ResolutionStatus

router = APIRouter(prefix="/api", tags=["books"])
logger = logging.getLogger(__name__)

READER_DICTIONARY_MEDIA_TYPES = {
    ".csv": "text/csv; charset=utf-8",
    ".dsl": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".u8": "text/plain; charset=utf-8",
}


def _artifact_http_exception(exc: ArtifactPathError) -> HTTPException:
    status_code = 403 if exc.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT else 404
    return HTTPException(status_code=status_code, detail=str(exc))


def get_pipeline():
    return PipelineService()


def _safe_book_response(book: dict) -> dict:
    payload = dict(book)
    payload["cover_path"] = ""
    return payload


def _safe_chapter_response(chapter: dict) -> dict:
    payload = dict(chapter)
    for field in ("raw_text_path", "cleaned_text_path", "translated_text_path", "audio_path"):
        payload[field] = "available" if payload.get(field) else None
    content_path = str(payload.get("content_html_path") or "")
    payload["content_html_path"] = (
        content_path if content_path.startswith("/book-assets/") else "available" if content_path else None
    )
    return payload


@router.get("/books", response_model=list[dict])
async def list_books(
    pipeline: PipelineService = Depends(get_pipeline),
):
    books = pipeline.list_books()
    return [_safe_book_response(book) for book in books]


@router.get("/library/books", response_model=dict)
async def list_translated_library_books(
    pipeline: PipelineService = Depends(get_pipeline),
):
    return {"books": [_safe_book_response(book) for book in pipeline.list_translated_book_summaries()]}


@router.post("/books", response_model=dict, status_code=201)
async def create_book(
    book: BookCreate,
    pipeline: PipelineService = Depends(get_pipeline),
):
    book_id = pipeline.create_book(
        title=book.title,
        author=book.author,
        source=book.source,
        source_url=book.source_url,
    )
    return _safe_book_response(pipeline.get_book(book_id))


@router.get("/books/{book_id}", response_model=dict)
async def get_book(
    book_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    book = pipeline.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return _safe_book_response(book)


@router.patch("/books/{book_id}", response_model=dict)
async def update_book(
    book_id: int,
    update: BookUpdate,
    pipeline: PipelineService = Depends(get_pipeline),
):
    book = pipeline.update_book(book_id, **update.model_dump(exclude_unset=True))
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return _safe_book_response(book)


@router.post("/books/{book_id}/cover", response_model=dict)
async def update_book_cover(
    book_id: int,
    cover: UploadFile = File(...),
    pipeline: PipelineService = Depends(get_pipeline),
):
    try:
        content = await read_upload_bytes_limited(cover, label="Cover upload")
        book = pipeline.update_book_cover(
            book_id,
            filename=cover.filename or "",
            content_type=cover.content_type or "",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await cover.close()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return _safe_book_response(book)


@router.delete("/books/{book_id}")
async def delete_book(
    book_id: int,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    if not pipeline.delete_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    record_audit_event(
        event_type="delete_book",
        severity="info",
        source="books",
        message="Book deleted",
        request=request,
        details={"book_id": book_id, "resource_type": "book", "result": "success"},
    )
    return {"message": "Book deleted"}


# ── Reader Dictionaries ───────────────────────────────────────────────────


@router.get("/reader/dictionaries", response_model=dict)
async def list_reader_dictionaries(
    pipeline: PipelineService = Depends(get_pipeline),
):
    return {"dictionaries": pipeline.list_reader_dictionaries()}


@router.post("/reader/dictionaries", response_model=dict, status_code=201)
async def upload_reader_dictionary(
    file: UploadFile = File(...),
    pipeline: PipelineService = Depends(get_pipeline),
):
    try:
        content = await read_upload_bytes_limited(file, label="Dictionary upload")
        return pipeline.save_reader_dictionary(
            filename=file.filename or "",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("/reader/dictionaries/{filename}/download")
async def download_reader_dictionary(
    filename: str,
    pipeline: PipelineService = Depends(get_pipeline),
):
    try:
        path = pipeline.get_reader_dictionary_path(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    media_type = READER_DICTIONARY_MEDIA_TYPES.get(Path(path).suffix.casefold(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=Path(path).name)


@router.delete("/reader/dictionaries/{filename}", response_model=dict)
async def delete_reader_dictionary(
    filename: str,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    try:
        deleted = pipeline.delete_reader_dictionary(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Dictionary not found")
    record_audit_event(
        event_type="delete_dictionary",
        severity="info",
        source="books",
        message="Reader dictionary deleted",
        request=request,
        details={"resource_type": "dictionary", "filename": filename, "result": "success"},
    )
    return {"message": "Dictionary deleted", "filename": filename}


# ── Reader State ──────────────────────────────────────────────────────────


@router.get("/books/{book_id}/reader/state", response_model=dict)
async def get_reader_state(
    book_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    state = pipeline.get_reader_state(book_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return state


@router.patch("/books/{book_id}/reader/progress", response_model=dict)
async def update_reader_progress(
    book_id: int,
    update: ReaderProgressUpdate,
    pipeline: PipelineService = Depends(get_pipeline),
):
    progress = pipeline.save_reader_progress(book_id, **update.model_dump())
    if progress is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"progress": progress}


@router.get("/books/{book_id}/annotations", response_model=dict)
async def list_reader_annotations(
    book_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    annotations = pipeline.list_reader_annotations(book_id)
    if annotations is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"annotations": annotations}


@router.post("/books/{book_id}/annotations/import", response_model=dict)
async def import_reader_annotations(
    book_id: int,
    request: ReaderAnnotationImportRequest,
    pipeline: PipelineService = Depends(get_pipeline),
):
    imported = pipeline.import_reader_annotations(
        book_id,
        annotations=[annotation.model_dump() for annotation in request.annotations],
    )
    if imported is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return imported


@router.post("/books/{book_id}/chapters/{chapter_id}/annotations", response_model=dict, status_code=201)
async def create_reader_annotation(
    book_id: int,
    chapter_id: int,
    annotation: ReaderAnnotationCreate,
    pipeline: PipelineService = Depends(get_pipeline),
):
    created = pipeline.create_reader_annotation(book_id, chapter_id, **annotation.model_dump())
    if created is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"annotation": created}


@router.patch("/books/{book_id}/annotations/{annotation_id}", response_model=dict)
async def update_reader_annotation(
    book_id: int,
    annotation_id: int,
    update: ReaderAnnotationUpdate,
    pipeline: PipelineService = Depends(get_pipeline),
):
    annotation = pipeline.update_reader_annotation(
        book_id,
        annotation_id,
        **update.model_dump(exclude_unset=True),
    )
    if annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"annotation": annotation}


@router.delete("/books/{book_id}/annotations/{annotation_id}", response_model=dict)
async def delete_reader_annotation(
    book_id: int,
    annotation_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    if not pipeline.delete_reader_annotation(book_id, annotation_id):
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"message": "Annotation deleted"}


@router.post("/books/{book_id}/reader/sync", response_model=dict)
async def sync_reader_state(
    book_id: int,
    request: ReaderSyncRequest,
    pipeline: PipelineService = Depends(get_pipeline),
):
    state = pipeline.sync_reader_state(
        book_id,
        device_id=request.device_id,
        last_sync_at=request.last_sync_at,
        progress=request.progress.model_dump() if request.progress else None,
        annotations=[annotation.model_dump() for annotation in request.annotations],
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return state


@router.get("/books/{book_id}/search", response_model=dict)
async def search_reader_book(
    book_id: int,
    q: str = Query(""),
    scope: str = Query("translation,notes,highlights"),
    case_sensitive: bool = Query(False),
    regex: bool = Query(False),
    whole_word: bool = Query(False),
    pipeline: PipelineService = Depends(get_pipeline),
):
    allowed_scopes = {"translation", "notes", "highlights"}
    scopes = {item.strip() for item in scope.split(",") if item.strip()}
    scopes = scopes & allowed_scopes if scopes else allowed_scopes
    if not scopes:
        scopes = allowed_scopes

    try:
        results = pipeline.search_reader_book(
            book_id,
            query=q,
            scopes=scopes,
            case_sensitive=case_sensitive,
            regex=regex,
            whole_word=whole_word,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if results is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"results": results}


@router.get("/books/{book_id}/reader/xray", response_model=dict)
async def get_reader_xray(
    book_id: int,
    chapter_id: int | None = Query(None),
    spoiler_mode: str = Query("no_spoiler", pattern="^(no_spoiler|allow_spoiler)$"),
    pipeline: PipelineService = Depends(get_pipeline),
):
    response = pipeline.get_reader_xray(
        book_id,
        chapter_id=chapter_id,
        spoiler_mode=spoiler_mode,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Book or chapter not found")
    return response


@router.post("/books/{book_id}/reader/xray/enrich", response_model=dict)
async def enrich_reader_xray(
    book_id: int,
    request: ReaderXrayEnrichRequest,
    http_request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    record_audit_event(
        event_type="reader_ai_start",
        severity="info",
        source="books",
        message="Reader X-Ray enrichment requested",
        request=http_request,
        details={
            "action": "xray_enrich",
            "book_id": book_id,
            "chapter_id": request.chapter_id or 0,
        },
    )
    try:
        response = pipeline.enrich_reader_xray(
            book_id,
            chapter_id=request.chapter_id,
            spoiler_mode=request.spoiler_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Reader X-Ray enrichment failed for book %s", book_id, exc_info=True)
        record_audit_event(
            event_type="reader_ai_failure",
            severity="warning",
            source="books",
            message="Reader X-Ray enrichment failed",
            request=http_request,
            details={"action": "xray_enrich", "book_id": book_id, "result": "failure"},
        )
        raise HTTPException(status_code=502, detail="Reader AI failed. Check provider settings and server logs.") from exc
    if response is None:
        raise HTTPException(status_code=404, detail="Book or chapter not found")
    return response


@router.get("/books/{book_id}/dictionary/lookup", response_model=dict)
async def lookup_reader_dictionary(
    book_id: int,
    q: str = Query(..., min_length=1),
    chapter_id: int | None = Query(None),
    include_online: bool = Query(True),
    pipeline: PipelineService = Depends(get_pipeline),
):
    try:
        response = pipeline.lookup_reader_dictionary(
            book_id,
            query=q,
            chapter_id=chapter_id,
            include_online=include_online,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail="Book or chapter not found")
    return response


@router.get("/books/{book_id}/dictionary/pack", response_model=dict)
async def get_reader_dictionary_pack(
    book_id: int,
    chapter_id: int | None = Query(None),
    pipeline: PipelineService = Depends(get_pipeline),
):
    response = pipeline.get_reader_dictionary_pack(
        book_id,
        chapter_id=chapter_id,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Book or chapter not found")
    return response


@router.post(
    "/books/{book_id}/chapters/{chapter_id}/reader/explain",
    response_model=ReaderExplainResponse,
)
async def explain_reader_selection(
    book_id: int,
    chapter_id: int,
    request: ReaderExplainRequest,
    http_request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    record_audit_event(
        event_type="reader_ai_start",
        severity="info",
        source="books",
        message="Reader explanation requested",
        request=http_request,
        details={"action": "explain", "book_id": book_id, "chapter_id": chapter_id},
    )
    try:
        response = pipeline.explain_reader_selection(
            book_id,
            chapter_id,
            text=request.text,
            context_before=request.context_before,
            context_after=request.context_after,
            spoiler_mode=request.spoiler_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Reader explanation failed for book %s chapter %s", book_id, chapter_id, exc_info=True)
        record_audit_event(
            event_type="reader_ai_failure",
            severity="warning",
            source="books",
            message="Reader explanation failed",
            request=http_request,
            details={"action": "explain", "book_id": book_id, "chapter_id": chapter_id, "result": "failure"},
        )
        raise HTTPException(status_code=502, detail="Reader AI failed. Check provider settings and server logs.") from exc

    if response is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return response


# ── Chapters ──────────────────────────────────────────────────────────────


@router.get("/books/{book_id}/chapters", response_model=list[dict])
async def list_chapters(
    book_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    return [_safe_chapter_response(chapter) for chapter in pipeline.list_chapters(book_id)]


@router.get("/books/{book_id}/chapters/{chapter_id}", response_model=dict)
async def get_chapter(
    book_id: int,
    chapter_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return _safe_chapter_response(chapter)


@router.get("/books/{book_id}/chapters/{chapter_id}/source")
async def get_chapter_source(
    book_id: int,
    chapter_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        text = pipeline.get_chapter_source(chapter_id)
    except ArtifactPathError as exc:
        if exc.status is ResolutionStatus.FILE_MISSING:
            return {"text": "", "chapter_id": chapter_id, "missing": True, "missing_reason": exc.status.value}
        raise _artifact_http_exception(exc) from exc
    if text is None:
        return {"text": "", "chapter_id": chapter_id, "missing": True}
    return {"text": text, "chapter_id": chapter_id, "missing": False}


@router.get("/books/{book_id}/chapters/{chapter_id}/translation")
async def get_chapter_translation(
    book_id: int,
    chapter_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        text = pipeline.get_chapter_translation(chapter_id)
    except ArtifactPathError as exc:
        if exc.status is ResolutionStatus.FILE_MISSING:
            return {"text": "", "chapter_id": chapter_id, "missing": True, "missing_reason": exc.status.value}
        raise _artifact_http_exception(exc) from exc
    if text is None:
        return {"text": "", "chapter_id": chapter_id, "missing": True}
    return {"text": text, "chapter_id": chapter_id, "missing": False}


@router.get("/books/{book_id}/chapters/{chapter_id}/content")
async def get_chapter_content(
    book_id: int,
    chapter_id: int,
    pipeline: PipelineService = Depends(get_pipeline),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    try:
        content = pipeline.get_chapter_content(chapter_id)
    except ArtifactPathError as exc:
        raise _artifact_http_exception(exc) from exc
    if content is None:
        raise HTTPException(status_code=404, detail="Translation not found")
    return {"chapter_id": chapter_id, **content}


@router.patch("/books/{book_id}/chapters/{chapter_id}/translation", response_model=dict)
async def update_chapter_translation(
    book_id: int,
    chapter_id: int,
    edit: TranslationEdit,
    pipeline: PipelineService = Depends(get_pipeline),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    success = pipeline.update_chapter_translation(chapter_id, edit.text)
    if not success:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {"message": "Translation updated"}


@router.delete("/books/{book_id}/chapters/{chapter_id}/translation", response_model=dict)
async def delete_chapter_translation(
    book_id: int,
    chapter_id: int,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    if not pipeline.delete_chapter_translation(book_id, chapter_id):
        raise HTTPException(status_code=404, detail="Chapter not found")
    record_audit_event(
        event_type="delete_translation",
        severity="info",
        source="books",
        message="Chapter translation deleted",
        request=request,
        details={
            "resource_type": "translation",
            "book_id": book_id,
            "chapter_id": chapter_id,
            "result": "success",
        },
    )
    return {"message": "Translation deleted"}


@router.delete("/books/{book_id}/chapters/{chapter_id}", response_model=dict)
async def delete_chapter(
    book_id: int,
    chapter_id: int,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
):
    if not pipeline.delete_chapter(book_id, chapter_id):
        raise HTTPException(status_code=404, detail="Chapter not found")
    record_audit_event(
        event_type="delete_chapter",
        severity="info",
        source="books",
        message="Chapter deleted",
        request=request,
        details={
            "resource_type": "chapter",
            "book_id": book_id,
            "chapter_id": chapter_id,
            "result": "success",
        },
    )
    return {"message": "Chapter deleted"}


@router.post("/books/{book_id}/chapters/{chapter_id}/paragraphs/{paragraph_index}/retranslate", response_model=dict)
async def retranslate_paragraph(
    book_id: int,
    chapter_id: int,
    paragraph_index: int,
    request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
    current_user: UserResponse = Depends(get_current_user),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    source_text = pipeline.get_chapter_source(chapter_id)
    if source_text is None:
        raise HTTPException(status_code=404, detail="Source text not found")
    source_paragraphs = [p.strip() for p in source_text.split("\n\n") if p.strip()]
    if paragraph_index < 0 or paragraph_index >= len(source_paragraphs):
        raise HTTPException(status_code=400, detail="Paragraph index out of range")

    translated_text = pipeline.get_chapter_translation(chapter_id)
    if translated_text is None:
        raise HTTPException(status_code=404, detail="Translation not found")
    translated_paragraphs = [p.strip() for p in translated_text.split("\n\n") if p.strip()]
    if paragraph_index < 0 or paragraph_index >= len(translated_paragraphs):
        raise HTTPException(status_code=400, detail="Translated paragraph index out of range")

    try:
        record_audit_event(
            event_type="reader_ai_start",
            severity="info",
            source="books",
            message="Paragraph retranslate requested",
            request=request,
            details={
                "action": "paragraph_retranslate",
                "book_id": book_id,
                "chapter_id": chapter_id,
                "paragraph_index": paragraph_index,
            },
        )
        paragraph_translation = pipeline.retranslate_paragraph(book_id, chapter_id, paragraph_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "Paragraph retranslate failed for book %s chapter %s paragraph %s",
            book_id,
            chapter_id,
            paragraph_index,
            exc_info=True,
        )
        record_audit_event(
            event_type="reader_ai_failure",
            severity="warning",
            source="books",
            message="Paragraph retranslate failed",
            request=request,
            details={
                "action": "paragraph_retranslate",
                "book_id": book_id,
                "chapter_id": chapter_id,
                "paragraph_index": paragraph_index,
                "result": "failure",
            },
        )
        raise HTTPException(
            status_code=502,
            detail="LLM retranslate failed. Check provider settings and server logs.",
        ) from exc

    if not pipeline.update_paragraph(chapter_id, paragraph_index, paragraph_translation):
        raise HTTPException(status_code=500, detail="Failed to update paragraph translation")

    return {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "paragraph_index": paragraph_index,
        "text": paragraph_translation,
    }


@router.post("/books/{book_id}/chapters/{chapter_id}/paragraphs/{paragraph_index}/polish", response_model=dict)
async def polish_paragraph(
    book_id: int,
    chapter_id: int,
    paragraph_index: int,
    request: ParagraphPolishRequest,
    http_request: Request,
    pipeline: PipelineService = Depends(get_pipeline),
    current_user: UserResponse = Depends(get_current_user),
):
    chapter = pipeline.get_chapter(chapter_id)
    if not chapter or chapter.get("book_id") != book_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    translated_text = pipeline.get_chapter_translation(chapter_id)
    if translated_text is None:
        raise HTTPException(status_code=404, detail="Translation not found")
    translated_paragraphs = [p.strip() for p in translated_text.split("\n\n") if p.strip()]
    if paragraph_index < 0 or paragraph_index >= len(translated_paragraphs):
        raise HTTPException(status_code=400, detail="Paragraph index out of range")

    try:
        record_audit_event(
            event_type="reader_ai_start",
            severity="info",
            source="books",
            message="Paragraph polish requested",
            request=http_request,
            details={
                "action": "paragraph_polish",
                "book_id": book_id,
                "chapter_id": chapter_id,
                "paragraph_index": paragraph_index,
            },
        )
        polished_paragraph = pipeline.polish_paragraph(
            book_id,
            chapter_id,
            paragraph_index,
            instructions=request.instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(
            "Paragraph polish failed for book %s chapter %s paragraph %s",
            book_id,
            chapter_id,
            paragraph_index,
            exc_info=True,
        )
        record_audit_event(
            event_type="reader_ai_failure",
            severity="warning",
            source="books",
            message="Paragraph polish failed",
            request=http_request,
            details={
                "action": "paragraph_polish",
                "book_id": book_id,
                "chapter_id": chapter_id,
                "paragraph_index": paragraph_index,
                "result": "failure",
            },
        )
        raise HTTPException(
            status_code=502,
            detail="LLM polish failed. Check provider settings and server logs.",
        ) from exc

    if not pipeline.update_paragraph(chapter_id, paragraph_index, polished_paragraph):
        raise HTTPException(status_code=500, detail="Failed to update paragraph translation")

    return {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "paragraph_index": paragraph_index,
        "text": polished_paragraph,
    }
