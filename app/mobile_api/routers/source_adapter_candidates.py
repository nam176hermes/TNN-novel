from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.database.db import get_source_adapter_candidate, list_source_adapter_candidates
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.schemas import SourceAdapterCandidate, SourceAdapterCandidateList

router = APIRouter(prefix="/api/source-adapter-candidates", tags=["source-adapter-candidates"])


@router.get("", response_model=SourceAdapterCandidateList)
async def list_candidates(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    return list_source_adapter_candidates(
        get_db_path(),
        page=page,
        per_page=page_size or per_page,
    )


@router.get("/{candidate_id}", response_model=SourceAdapterCandidate)
async def get_candidate(candidate_id: str):
    candidate = get_source_adapter_candidate(get_db_path(), candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Parser candidate not found")
    return candidate
