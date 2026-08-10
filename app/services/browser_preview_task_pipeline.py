"""In-memory staged source-preview execution for the durable worker."""

from __future__ import annotations

from threading import RLock

from app.database.import_jobs import ImportJobRepository, TaskStage
from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
    PreviewBrowserPayload,
    encode_browser_result,
)
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.services.pipeline_service import PipelineService


class BrowserPreviewTaskPipeline:
    """Keep preview payloads in process until their durable result is published."""

    def __init__(self, repository: ImportJobRepository, pipeline: PipelineService) -> None:
        self.repository = repository
        self.pipeline = pipeline
        self._payloads: dict[int, PreviewBrowserPayload] = {}
        self._lock = RLock()

    def run_stage(self, stage, task, *, cancel_check):
        if cancel_check():
            return None
        job = self.repository.get_job_internal(task.job_id)
        if job is None or job.operation_kind is not ImportOperationKind.PREVIEW:
            raise SourceAdapterError(
                "Preview job is unavailable",
                code=FetchErrorCode.INTERNAL_ERROR,
                retryable=False,
                http_status=500,
            )

        if stage is TaskStage.FETCHING:
            preview = dict(self.pipeline.preview_source_url(job.source_url))
            preview.pop("chapter_count", None)
            payload = PreviewBrowserPayload.model_validate(preview)
            with self._lock:
                self._payloads[task.id] = payload
            return None

        payload = self._payload(task.id)
        if stage is TaskStage.PARSING:
            return None
        if stage is TaskStage.VALIDATING:
            validated = PreviewBrowserPayload.model_validate(payload.model_dump(mode="python"))
            encode_browser_result(
                BrowserTaskResult(
                    correlation_id=job.correlation_id,
                    state=BrowserResultState.COMPLETED,
                    payload=validated,
                )
            )
            with self._lock:
                self._payloads[task.id] = validated
            return None
        if stage is TaskStage.IMPORTING:
            return BrowserTaskResult(
                correlation_id=job.correlation_id,
                state=BrowserResultState.COMPLETED,
                payload=payload,
            )
        return None

    def release_task(self, task_id: int) -> None:
        with self._lock:
            self._payloads.pop(task_id, None)

    def _payload(self, task_id: int) -> PreviewBrowserPayload:
        with self._lock:
            payload = self._payloads.get(task_id)
        if payload is None:
            raise SourceAdapterError(
                "Fetched preview state is unavailable",
                code=FetchErrorCode.INTERNAL_ERROR,
                retryable=False,
                http_status=500,
            )
        return payload
