from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.database.glossary_repository import GlossaryStateConflict, GlossaryValidationError
from app.mobile_api.audit import record_audit_event
from app.mobile_api.schemas import (
    GlossaryBulkRequest,
    GlossaryMergeApplyRequest,
    GlossaryMergePreviewRequest,
    GlossaryTermCreate,
    GlossaryTermUpdate,
    ImportGlossaryResponse,
    TranslationMemoryEntryCreate,
)
from app.mobile_api.services.glossary_service import GlossaryService

router = APIRouter(prefix="/api/glossary", tags=["glossary"])
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000


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
        detail = {"code": exc.code}
        if exc.code == "normalized_source_collision":
            detail["resolution"] = "archive_active_canonical_first"
        raise HTTPException(status_code=409, detail=detail) from None


def _validated_mutation(call):
    try:
        return _state_mutation(call)
    except GlossaryValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "errors": exc.errors},
        ) from None


async def _bounded_json(request: Request):
    body = await request.body()
    if len(body) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large"})
    try:
        return json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_json"}) from None


def _csv_import_item(row: dict[str, str], item_number: int) -> dict:
    if None in row or any(value is None for value in row.values()):
        raise HTTPException(status_code=422, detail={"code": "invalid_csv"})
    if row.get("schema_version") != "1":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_failed",
                "errors": [{"item": item_number, "field": "schema_version", "code": "unsupported"}],
            },
        )
    if row.get("scope") not in {"all", "book", "global"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
    item = {
        key: value
        for key, value in row.items()
        if key not in {"schema_version", "scope", "scope_book_id"} and value != ""
    }
    for field in (
        "id", "book_id", "approved", "locked", "occurrence_count", "priority",
        "first_seen_chapter_id", "first_seen_chapter_number", "version",
    ):
        if field in item:
            try:
                item[field] = int(item[field])
            except (TypeError, ValueError, OverflowError):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "validation_failed",
                        "errors": [{"item": item_number, "field": field, "code": "invalid_number"}],
                    },
                ) from None
    if "confidence" in item:
        try:
            item["confidence"] = float(item["confidence"])
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_failed",
                    "errors": [{"item": item_number, "field": "confidence", "code": "invalid_number"}],
                },
            ) from None
    if "archived" in item:
        archived = str(item["archived"]).strip().lower()
        if archived not in {"true", "false"}:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_failed",
                    "errors": [{"item": item_number, "field": "archived", "code": "invalid_value"}],
                },
            )
        item["archived"] = archived == "true"
    _validate_import_scope(row["scope"], row.get("scope_book_id"), [item], csv_value=True)
    return item


def _validate_import_scope(
    scope_type: str,
    scope_book_id,
    items: list[dict],
    *,
    csv_value: bool = False,
) -> None:
    if scope_type not in {"all", "book", "global"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
    if scope_book_id is None or scope_book_id == "":
        if scope_type == "book":
            raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
        expected_book_id = 0
    else:
        if isinstance(scope_book_id, bool):
            raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
        try:
            expected_book_id = int(scope_book_id) if csv_value else scope_book_id
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(status_code=422, detail={"code": "invalid_scope"}) from None
        if type(expected_book_id) is not int or not 0 <= expected_book_id <= 2**63 - 1:
            raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
    if scope_type == "all":
        return
    if scope_type == "global":
        if expected_book_id != 0:
            raise HTTPException(status_code=422, detail={"code": "scope_mismatch"})
        expected_book_id = 0
    for item in items:
        item_book_id = item.get("book_id", 0) if isinstance(item, dict) else None
        if type(item_book_id) is int and item_book_id != expected_book_id:
            raise HTTPException(status_code=422, detail={"code": "scope_mismatch"})


async def _bounded_import_payload(request: Request) -> tuple[dict, bool]:
    body = await request.body()
    if len(body) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large"})
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type in {"text/csv", "application/csv"}:
        try:
            text = body.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            required = {"schema_version", "scope", "source_term", "target_term"}
            if (
                not reader.fieldnames
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or not required.issubset(reader.fieldnames)
            ):
                raise HTTPException(status_code=422, detail={"code": "invalid_csv_schema"})
            rows = [_csv_import_item(row, index) for index, row in enumerate(reader, start=1)]
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail={"code": "invalid_csv"}) from None
        return {"items": _bounded_items(rows)}, True
    try:
        payload = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_json"}) from None
    if isinstance(payload, list):
        payload = {"items": payload}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail={"code": "object_required"})
    if "schema_version" in payload and payload["schema_version"] != 1:
        raise HTTPException(status_code=422, detail={"code": "unsupported_schema_version"})
    if "scope" in payload:
        scope = payload["scope"]
        if not isinstance(scope, dict) or scope.get("type") not in {"all", "book", "global"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_scope"})
    if "items" not in payload and "terms" in payload:
        payload = {**payload, "items": payload["terms"]}
    payload["items"] = _bounded_items(payload.get("items"))
    if "scope" in payload:
        _validate_import_scope(
            payload["scope"]["type"], payload["scope"].get("book_id"), payload["items"]
        )
    return payload, False


def _bounded_items(value) -> list[dict]:
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail={"code": "items_required"})
    if len(value) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422, detail={"code": "row_limit_exceeded"})
    return value


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
    archived: bool = Query(False),
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
        archived=archived,
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
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    include_legacy: bool = Query(True),
    legacy_member_limit: int = Query(20, ge=1, le=50),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """List bounded global/book, primary/variant, and normalized conflicts."""
    result = svc.query_conflicts(book_id, page, per_page)
    legacy = (
        svc.query_legacy_conflicts(book_id, page, per_page, legacy_member_limit)
        if include_legacy
        else []
    )
    return {**result, "conflicts": legacy, "legacy_bounded": True}


@router.post("/conflicts/merge/preview", response_model=dict)
async def preview_conflict_merge(
    merge: GlossaryMergePreviewRequest,
    svc: GlossaryService = Depends(get_glossary_service),
):
    return _state_mutation(
        lambda: svc.preview_merge(merge.canonical_id, merge.duplicate_ids)
    )


@router.post("/conflicts/merge/apply", response_model=dict)
async def apply_conflict_merge(
    merge: GlossaryMergeApplyRequest,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    actor, request_id = _mutation_metadata(request)
    return _state_mutation(
        lambda: svc.apply_merge(
            merge.canonical_id,
            merge.duplicate_ids,
            merge.digest,
            actor=actor,
            request_id=request_id,
        )
    )


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


@router.post("/terms/bulk", response_model=dict)
async def bulk_terms(
    bulk: GlossaryBulkRequest,
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    actor, request_id = _mutation_metadata(request)
    return _state_mutation(
        lambda: svc.bulk_terms(
            bulk.action,
            [term.model_dump() for term in bulk.terms],
            actor=actor,
            request_id=request_id,
        )
    )


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


@router.post("/import/preview", response_model=dict)
async def preview_import_glossary(
    request: Request,
    conflict_policy: str = Query(""),
    svc: GlossaryService = Depends(get_glossary_service),
):
    payload, csv_payload = await _bounded_import_payload(request)
    items = payload["items"]
    policy = (
        (conflict_policy or "skip_conflicts")
        if csv_payload
        else str(payload.get("conflict_policy") or "skip_conflicts")
    )
    return _validated_mutation(lambda: svc.preview_import(items, policy))


@router.post("/import/apply", response_model=dict)
async def apply_import_glossary(
    request: Request,
    digest: str = Query(""),
    conflict_policy: str = Query(""),
    svc: GlossaryService = Depends(get_glossary_service),
):
    payload, csv_payload = await _bounded_import_payload(request)
    items = payload["items"]
    resolved_digest = digest if csv_payload else str(payload.get("digest") or "")
    if len(resolved_digest) != 64:
        raise HTTPException(status_code=422, detail={"code": "digest_required"})
    policy = (
        conflict_policy or "skip_conflicts"
        if csv_payload
        else str(payload.get("conflict_policy") or "skip_conflicts")
    )
    actor, request_id = _mutation_metadata(request)
    return _validated_mutation(
        lambda: svc.apply_import(
            items,
            resolved_digest,
            policy,
            actor=actor,
            request_id=request_id,
        )
    )


@router.post("/import", response_model=ImportGlossaryResponse)
async def import_glossary(
    request: Request,
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Bounded legacy adapter over atomic preview/apply."""
    data = _bounded_items(await _bounded_json(request))
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
    scope: Literal["all", "book", "global"] | None = Query(None),
    svc: GlossaryService = Depends(get_glossary_service),
):
    """Export glossary as JSON or CSV."""
    resolved_scope = scope or ("book" if book_id is not None else "all")
    if resolved_scope == "book" and book_id is None:
        raise HTTPException(status_code=422, detail={"code": "book_id_required"})
    terms = svc.export_glossary(book_id, resolved_scope)
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
        output = io.StringIO()
        fieldnames = ["schema_version", "scope", "scope_book_id", *(terms[0].keys() if terms else [])]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {
                "schema_version": 1,
                "scope": resolved_scope,
                "scope_book_id": book_id or 0,
                **term,
            }
            for term in terms
        )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=glossary.csv"},
        )
    return {
        "schema_version": 1,
        "scope": {"type": resolved_scope, "book_id": book_id or 0},
        "terms": terms,
        "total": len(terms),
    }
