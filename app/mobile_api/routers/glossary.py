from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.database.glossary_repository import GlossaryStateConflict
from app.mobile_api.audit import record_audit_event
from app.mobile_api.schemas import (
    GlossaryTermCreate,
    GlossaryTermUpdate,
    ImportGlossaryResponse,
    TranslationMemoryEntryCreate,
)
from app.mobile_api.services.glossary_service import GlossaryService

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


def get_glossary_service():
    return GlossaryService()


def _mutation_metadata(request: Request) -> tuple[str, str]:
    user = getattr(request.state, "user", {})
    request_id = request.headers.get("X-Request-ID", "") or request.headers.get("X-Correlation-ID", "")
    return str(user.get("username") or ""), request_id


def _state_mutation(call):
    try:
        return call()
    except GlossaryStateConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from None


@router.get("")
async def list_glossary(
    book_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: str = Query("", max_length=200),
    review_status: str = Query("", max_length=120),
    term_type: str | None = Query(None, max_length=40),
    mode: str | None = Query(None),
    locked: bool | None = Query(None),
    scope: Literal["all", "book", "global", "effective"] | None = Query(None),
    sort: Literal[
        "review", "source_asc", "source_desc", "updated_desc", "updated_asc", "priority_desc", "evidence_desc"
    ] = Query("review"),
    approved: int | None = Query(None),
    include_weak: bool | None = Query(None),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """List a bounded glossary review page using SQL filters and facets."""
    statuses = tuple(part.strip().upper() for part in review_status.split(",") if part.strip())
    if any(status not in {"NEEDS_REVIEW", "APPROVED", "REJECTED", "LOCKED", "CONFLICT"} for status in statuses):
        raise HTTPException(status_code=422, detail={"code": "invalid_review_status"})
    if mode is not None and mode not in {"", "translate", "context", "transliterate"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_mode"})
    if scope in {"book", "effective"} and book_id is None:
        raise HTTPException(status_code=422, detail={"code": "book_id_required"})

    legacy_call = approved is not None or include_weak is not None
    resolved_scope = scope or ("legacy" if legacy_call else ("effective" if book_id is not None else "all"))
    return svc.query_terms(
        book_id=book_id,
        page=page,
        per_page=per_page,
        q=q,
        review_status=review_status,
        term_type=term_type,
        mode=mode,
        locked=locked,
        scope=resolved_scope,
        sort=sort,
        approved=approved,
        include_weak=bool(include_weak),
    )


@router.get("/search")
async def search_glossary(
    q: str = Query(..., min_length=1),
    book_id: int | None = Query(None),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Search glossary terms."""
    results = svc.search_terms(q, book_id)
    return {"results": results, "total": len(results)}


@router.get("/conflicts")
async def list_glossary_conflicts(
    book_id: int | None = Query(None),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """List glossary conflicts and target reuse warnings."""
    conflicts = svc.get_conflicts(book_id)
    return {"conflicts": conflicts, "total": len(conflicts)}


@router.post("/tm", response_model=dict, status_code=201)
async def add_tm_entry(
    entry: TranslationMemoryEntryCreate,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Add or update a fuzzy translation memory entry."""
    source_text = entry.source_text.strip()
    translation_text = entry.translation_text.strip()
    if not source_text or not translation_text:
        raise HTTPException(status_code=400, detail="source_text and translation_text are required")

    entry_id = svc.add_tm_entry(
        source_text=source_text,
        translation_text=translation_text,
        score=entry.score,
        book_id=entry.book_id,
        chapter_number=entry.chapter_number,
        source_lang=entry.source_lang,
        target_lang=entry.target_lang,
    )
    return {"id": entry_id, "message": "TM entry added"}


@router.get("/tm/search")
async def search_tm(
    q: str = Query(..., min_length=1),
    threshold: int = Query(80, ge=0, le=100),
    limit: int = Query(10, ge=1, le=100),
    book_id: int | None = Query(None),
    source_lang: str = Query("zh"),
    target_lang: str = Query("vi"),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Search fuzzy translation memory."""
    results = svc.search_tm(
        q,
        threshold=threshold,
        limit=limit,
        book_id=book_id,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    return {"results": results, "total": len(results)}


@router.delete("/tm", response_model=dict)
async def clear_tm(
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Clear fuzzy translation memory."""
    deleted = svc.clear_tm()
    record_audit_event(
        event_type="delete_tm",
        severity="info",
        source="glossary",
        message="Translation memory cleared",
        request=request,
        details={"resource_type": "translation_memory", "deleted": deleted, "result": "success"},
    )
    return {"deleted": deleted}


@router.post("/terms", response_model=dict, status_code=201)
async def add_term(
    term: GlossaryTermCreate,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Add a new glossary term."""
    actor, request_id = _mutation_metadata(request)
    resource = _state_mutation(
        lambda: svc.add_term_resource(term.model_dump(), actor=actor, request_id=request_id)
    )
    return {**resource, "message": "Term added"}


@router.get("/terms/{term_id}", response_model=dict)
async def get_term_detail(
    term_id: int,
    svc: GlossaryService = Depends(get_glossary_service),
):
    resource = svc.get_term_detail(term_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Term not found")
    return resource


@router.patch("/terms/{term_id}", response_model=dict)
async def update_term(
    term_id: int,
    update: GlossaryTermUpdate,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Update a glossary term."""
    actor, request_id = _mutation_metadata(request)
    resource = _state_mutation(
        lambda: svc.update_term_resource(
            term_id,
            update.model_dump(exclude_none=True),
            actor=actor,
            request_id=request_id,
        )
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Term not found")
    return {**resource, "message": "Term updated"}


@router.post("/terms/{term_id}/lock", response_model=dict)
async def lock_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Lock a glossary term so translation prompts treat it as non-negotiable."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.set_term_locked(term_id, True, actor=actor, request_id=request_id)
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"message": "Term locked"}


@router.post("/terms/{term_id}/unlock", response_model=dict)
async def unlock_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Unlock a glossary term."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.set_term_locked(term_id, False, actor=actor, request_id=request_id)
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"message": "Term unlocked"}


@router.delete("/terms/{term_id}", response_model=dict)
async def delete_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Delete a glossary term."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.delete_term(
            term_id,
            actor=actor,
            request_id=request_id,
        )
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    record_audit_event(
        event_type="delete_glossary_term",
        severity="info",
        source="glossary",
        message="Glossary term deleted",
        request=request,
        details={"resource_type": "glossary_term", "term_id": term_id, "result": "success"},
    )
    return {"message": "Term deleted"}


@router.post("/terms/{term_id}/restore", response_model=dict)
async def restore_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Restore an archived glossary term."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.restore_term(
            term_id,
            actor=actor,
            request_id=request_id,
        )
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"message": "Term restored"}


@router.post("/terms/{term_id}/approve", response_model=dict)
async def approve_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Approve a pending glossary term."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.approve_term(term_id, actor=actor, request_id=request_id)
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found or already approved")
    return {"message": "Term approved"}


@router.post("/terms/{term_id}/reject", response_model=dict)
async def reject_term(
    term_id: int,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Reject a pending glossary term."""
    actor, request_id = _mutation_metadata(request)
    success = _state_mutation(
        lambda: svc.reject_term(term_id, actor=actor, request_id=request_id)
    )
    if not success:
        raise HTTPException(status_code=404, detail="Term not found or already approved")
    return {"message": "Term rejected"}


@router.post("/import", response_model=ImportGlossaryResponse)
async def import_glossary(
    data: list[dict],
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Import glossary from JSON."""
    actor, request_id = _mutation_metadata(request)
    result = svc.import_glossary(data, actor=actor, request_id=request_id)
    record_audit_event(
        event_type="import_complete",
        severity="info",
        source="glossary",
        message="Glossary import completed",
        request=request,
        details={
            "import_type": "glossary",
            "term_count": len(data),
            "result": "success",
        },
    )
    return ImportGlossaryResponse(**result)


@router.get("/export")
async def export_glossary(
    request: Request,
    book_id: int | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Export glossary as JSON or CSV."""
    terms = svc.export_glossary(book_id)
    record_audit_event(
        event_type="export_download",
        severity="info",
        source="glossary",
        message="Glossary export downloaded",
        request=request,
        details={
            "resource_type": "glossary",
            "book_id": book_id or 0,
            "format": format,
            "term_count": len(terms),
            "result": "success",
        },
    )
    if format == "csv":
        import csv
        import io
        output = io.StringIO()
        if terms:
            writer = csv.DictWriter(output, fieldnames=list(terms[0].keys()))
            writer.writeheader()
            writer.writerows(terms)
        from fastapi.responses import Response
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=glossary.csv"},
        )
    return {"terms": terms, "total": len(terms)}
