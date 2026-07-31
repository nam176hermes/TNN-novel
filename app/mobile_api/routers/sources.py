from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.database.db import (
    get_managed_source,
    list_managed_source_tests,
    list_managed_sources,
    update_managed_source,
)
from app.ingestion.managed_sources import (
    import_selected_catalog_sources,
    test_existing_managed_source,
    validate_managed_source_update,
    verify_managed_source,
)
from app.ingestion.source_adapters import SourceAdapterError
from app.mobile_api.audit import record_audit_event
from app.mobile_api.auth import get_current_user
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.schemas import (
    ManagedSource,
    ManagedSourceImportRequest,
    ManagedSourceImportSummary,
    ManagedSourceList,
    ManagedSourceTestResponse,
    ManagedSourceUpdateRequest,
)

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _source_not_found(source_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Managed source {source_id} not found")


@router.get("", response_model=ManagedSourceList)
async def list_sources(
    query: str = Query(default="", max_length=200),
    status: str = Query(default="", max_length=32),
    trust_level: str = Query(default="", max_length=32),
    language: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    del current_user
    payload = list_managed_sources(
        get_db_path(),
        query=query,
        status=status,
        trust_level=trust_level,
        language=language,
        page=page,
        per_page=page_size,
    )
    payload["page_size"] = payload.get("per_page", page_size)
    return payload


@router.get("/{source_id}", response_model=ManagedSource)
async def get_source(source_id: str, current_user: dict = Depends(get_current_user)):
    del current_user
    source = get_managed_source(get_db_path(), source_id)
    if source is None:
        raise _source_not_found(source_id)
    return source


@router.get("/{source_id}/tests", response_model=list[ManagedSourceTestResponse])
async def get_source_tests(source_id: str, current_user: dict = Depends(get_current_user)):
    del current_user
    if get_managed_source(get_db_path(), source_id) is None:
        raise _source_not_found(source_id)
    return list_managed_source_tests(get_db_path(), source_id, limit=20)


@router.post("/import-catalog", response_model=ManagedSourceImportSummary)
async def import_catalog_sources(
    payload: ManagedSourceImportRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    try:
        summary = import_selected_catalog_sources(get_db_path(), payload.entry_ids)
    except SourceAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_event(
        event_type="source_import",
        severity="info",
        source="sources",
        message="Imported selected source catalog entries",
        request=request,
        details={
            "selected": summary.selected,
            "inserted": summary.inserted,
            "duplicates": summary.duplicates,
            "invalid": summary.invalid,
        },
    )
    return summary.to_dict()


@router.patch("/{source_id}", response_model=ManagedSource)
async def patch_source(
    source_id: str,
    payload: ManagedSourceUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    try:
        updates = validate_managed_source_update(payload.model_dump(exclude_none=True))
    except SourceAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = update_managed_source(get_db_path(), source_id, **updates)
    if updated is None:
        raise _source_not_found(source_id)
    record_audit_event(
        event_type="source_update",
        severity="info",
        source="sources",
        message="Managed source updated",
        request=request,
        details={"source_id": source_id, "fields": sorted(updates)},
    )
    return updated


@router.post("/{source_id}/test", response_model=ManagedSourceTestResponse)
async def test_source(
    source_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    try:
        result = test_existing_managed_source(get_db_path(), source_id)
    except SourceAdapterError as exc:
        status_code = 409 if "cannot be tested" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    record_audit_event(
        event_type="source_test",
        severity="warning" if result["status"] != "success" else "info",
        source="sources",
        message="Managed source test completed",
        request=request,
        details={
            "source_id": source_id,
            "status": result["status"],
            "reason": result["reason"],
            "http_status": result.get("http_status"),
        },
    )
    return result


@router.post("/{source_id}/verify", response_model=ManagedSource)
async def verify_source(
    source_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    try:
        updated = verify_managed_source(get_db_path(), source_id)
    except SourceAdapterError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        event_type="source_verify",
        severity="info",
        source="sources",
        message="Managed source verified",
        request=request,
        details={"source_id": source_id, "status": updated.get("status", "")},
    )
    return updated


@router.post("/{source_id}/status", response_model=ManagedSource)
async def set_source_status(
    source_id: str,
    payload: ManagedSourceUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    next_status = str(payload.status or "").strip().upper()
    if next_status not in {"BROKEN", "BLOCKED", "NEEDS_REVIEW"}:
        raise HTTPException(status_code=400, detail="Unsupported source status update")
    updated = update_managed_source(get_db_path(), source_id, status=next_status)
    if updated is None:
        raise _source_not_found(source_id)
    record_audit_event(
        event_type="source_status_update",
        severity="warning" if next_status in {"BROKEN", "BLOCKED"} else "info",
        source="sources",
        message="Managed source status updated",
        request=request,
        details={"source_id": source_id, "status": next_status},
    )
    return updated
