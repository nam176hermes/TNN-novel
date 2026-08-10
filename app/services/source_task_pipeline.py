"""Dispatch durable source work without changing chapter-import behavior."""

from __future__ import annotations

from app.database.import_jobs import ImportJobRepository
from app.import_contracts import ImportOperationKind
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.services.pipeline_service import PipelineService
from app.observability import Observability
from app.services.browser_preview_task_pipeline import BrowserPreviewTaskPipeline
from app.services.source_import_task_pipeline import SourceImportTaskPipeline


class SourceTaskPipeline:
    """Select the operation-specific staged pipeline from durable job metadata."""

    def __init__(
        self,
        repository: ImportJobRepository,
        pipeline: PipelineService,
        *,
        observability: Observability | None = None,
        max_chapter_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.repository = repository
        self.chapter_pipeline = SourceImportTaskPipeline(
            repository,
            pipeline,
            observability=observability,
            max_chapter_bytes=max_chapter_bytes,
        )
        self.preview_pipeline = BrowserPreviewTaskPipeline(repository, pipeline)

    def run_stage(self, stage, task, *, cancel_check):
        if cancel_check():
            return None
        job = self.repository.get_job_internal(task.job_id)
        if job is None:
            raise SourceAdapterError(
                "Source job is unavailable",
                code=FetchErrorCode.INTERNAL_ERROR,
                retryable=False,
                http_status=500,
            )
        if job.operation_kind is ImportOperationKind.PREVIEW:
            return self.preview_pipeline.run_stage(
                stage,
                task,
                cancel_check=cancel_check,
            )
        return self.chapter_pipeline.run_stage(
            stage,
            task,
            cancel_check=cancel_check,
        )

    def release_task(self, task_id: int) -> None:
        self.chapter_pipeline.release_task(task_id)
        self.preview_pipeline.release_task(task_id)
