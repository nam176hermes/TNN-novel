from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.database.db import (
    get_source_catalog_entry,
    insert_source_adapter_candidate,
    list_source_catalog_entries,
    record_source_catalog_health_check,
)
from app.ingestion.parser_candidates import create_parser_candidate
from app.ingestion.source_health import check_source_health
from app.mobile_api.audit import record_audit_event
from app.mobile_api.auth import get_current_user
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.schemas import (
    ParserCandidateCreateRequest,
    SourceAdapterCandidate,
    SourceCatalogHealthResponse,
    SourceCatalogList,
)

router = APIRouter(prefix="/api/source-catalog", tags=["source-catalog"])


def _parse_supported_filter(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "supported"}:
        return True
    if normalized in {"0", "false", "no", "unsupported"}:
        return False
    return None


def _catalog_response(payload: dict) -> dict:
    entries = payload.get("items", [])
    payload["entries"] = entries
    payload["page_size"] = payload.get("per_page", 50)
    return payload


@router.get("", response_model=SourceCatalogList)
async def list_source_catalog(
    query: str = Query(default="", max_length=200),
    tag: str = Query(default="", max_length=32),
    domain: str = Query(default="", max_length=255),
    supported: str | None = Query(default=None, max_length=32),
    status: str = Query(default="", max_length=32),
    trust_level: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    page_size: int | None = Query(default=None, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """Return read-only metadata about known external source catalog entries."""
    del current_user
    return _catalog_response(
        list_source_catalog_entries(
            get_db_path(),
            query=query,
            tag=tag,
            domain=domain,
            supported=_parse_supported_filter(supported),
            managed_status=status,
            managed_trust_level=trust_level,
            page=page,
            per_page=page_size or per_page,
        )
    )


@router.get("/", response_model=SourceCatalogList, include_in_schema=False)
async def list_source_catalog_slash(
    query: str = Query(default="", max_length=200),
    tag: str = Query(default="", max_length=32),
    domain: str = Query(default="", max_length=255),
    supported: str | None = Query(default=None, max_length=32),
    status: str = Query(default="", max_length=32),
    trust_level: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    page_size: int | None = Query(default=None, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    del current_user
    return await list_source_catalog(
        query=query,
        tag=tag,
        domain=domain,
        supported=supported,
        status=status,
        trust_level=trust_level,
        page=page,
        per_page=per_page,
        page_size=page_size,
    )


@router.post("/{entry_id}/check", response_model=SourceCatalogHealthResponse)
async def check_source_catalog_entry(entry_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    del current_user
    db_path = get_db_path()
    entry = get_source_catalog_entry(db_path, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Source catalog entry not found")

    result = check_source_health(entry)
    payload = result.to_dict()
    record_source_catalog_health_check(db_path, payload)
    record_audit_event(
        event_type="source_catalog_health_check",
        severity="warning" if result.status in {"blocked", "timeout", "captcha", "error"} else "info",
        source="source_catalog",
        message="Source catalog health check completed",
        request=request,
        details={
            "catalog_entry_id": result.catalog_entry_id,
            "domain": result.domain,
            "status": result.status,
            "reason": result.reason,
            "http_status": result.http_status,
        },
    )
    return payload


@router.post("/{entry_id}/parser-candidate", response_model=SourceAdapterCandidate)
async def create_source_catalog_parser_candidate(
    entry_id: str,
    request: Request,
    payload: ParserCandidateCreateRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    del current_user
    db_path = get_db_path()
    entry = get_source_catalog_entry(db_path, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Source catalog entry not found")

    candidate = create_parser_candidate(entry, sample_url=(payload.sample_url if payload else ""))
    inserted = insert_source_adapter_candidate(db_path, candidate)
    record_audit_event(
        event_type="source_parser_candidate_create",
        severity="warning" if inserted.get("parser_confidence") == "failed" else "info",
        source="source_catalog",
        message="Source parser candidate created",
        request=request,
        details={
            "catalog_entry_id": inserted.get("catalog_entry_id", ""),
            "candidate_id": inserted.get("id", ""),
            "domain": inserted.get("domain", ""),
            "parser_confidence": inserted.get("parser_confidence", ""),
            "status": inserted.get("status", ""),
            "failure_reason": inserted.get("failure_reason", ""),
        },
    )
    return inserted
