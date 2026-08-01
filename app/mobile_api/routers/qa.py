from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.mobile_api.audit import record_audit_event
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAPersistenceError, QAService

router = APIRouter(prefix="/api", tags=["qa"])


def get_qa_service():
    return QAService(PipelineService())


@router.get("/books/{book_id}/chapters/{chapter_id}/qa", response_model=dict)
async def get_qa_report(
    book_id: int,
    chapter_id: int,
    svc: QAService = Depends(get_qa_service),
):
    """Get existing QA report for a chapter."""
    report = svc.get_qa_report(book_id, chapter_id)
    if report is None:
        return Response(status_code=204)
    return report


@router.get("/books/{book_id}/qa/summary", response_model=dict)
async def get_qa_summary(
    book_id: int,
    svc: QAService = Depends(get_qa_service),
):
    """Get QA summary for a book."""
    return svc.get_book_qa_summary(book_id)


@router.post("/books/{book_id}/chapters/{chapter_id}/qa/run", response_model=dict)
async def run_qa_check(
    book_id: int,
    chapter_id: int,
    request: Request,
    svc: QAService = Depends(get_qa_service),
):
    """Run QA check on a chapter."""
    record_audit_event(
        event_type="qa_start",
        severity="info",
        source="qa",
        message="QA check requested",
        request=request,
        details={"book_id": book_id, "chapter_id": chapter_id},
    )
    try:
        result = svc.run_qa_check(book_id, chapter_id)
        return result
    except QAPersistenceError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc
    except ValueError as exc:
        record_audit_event(
            event_type="qa_failure",
            severity="warning",
            source="qa",
            message="QA check failed",
            request=request,
            details={"book_id": book_id, "chapter_id": chapter_id, "result": "failure"},
        )
        raise HTTPException(status_code=404, detail=str(exc))
