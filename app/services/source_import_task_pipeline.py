"""Real source adapter for the durable import-job worker.

Only safe metadata is persisted by the worker.  Extracted chapter text stays
in process between fetch/validation and the serialized import stage.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from app.database.import_jobs import ImportJobRepository, TaskStage
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError, SourceChapterContent
from app.mobile_api.services.import_metadata import normalize_import_text
from app.mobile_api.services.pipeline_service import PipelineService
from app.observability import Observability, default_observability
from app.services.import_job_service import TaskImportOutcome


class SourceImportTaskPipeline:
    """Bridge ``PipelineService`` into the P06/P07 staged worker contract."""

    def __init__(
        self,
        repository: ImportJobRepository,
        pipeline: PipelineService,
        *,
        observability: Observability | None = None,
        max_chapter_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.repository = repository
        self.pipeline = pipeline
        self.observability = observability or default_observability
        self.max_chapter_bytes = max(1, int(max_chapter_bytes))
        self._chapters: dict[int, SourceChapterContent] = {}
        self._lock = RLock()

    def run_stage(self, stage, task, *, cancel_check):
        if cancel_check():
            return None
        if stage is TaskStage.FETCHING:
            job = self.repository.get_job_internal(task.job_id)
            adapter_id = (job.source if job else "") or "unknown"
            fetch_method = task.fetch_method or "direct_http"
            if not self.observability.circuit_breaker.allow(adapter_id, fetch_method):
                raise SourceAdapterError(
                    "The source is temporarily unavailable. Try again later.",
                    code=FetchErrorCode.SOURCE_UNAVAILABLE,
                    retryable=True,
                    http_status=503,
                )
            fetch_chapter = getattr(self.pipeline, "fetch_source_chapter", None)
            if not callable(fetch_chapter):
                raise SourceAdapterError(
                    "Chapter import failed. Check the source metadata and try again.",
                    code=FetchErrorCode.IMPORT_FAILED,
                    retryable=False,
                    http_status=500,
                )
            try:
                chapter = fetch_chapter(task.canonical_chapter_url)
            except SourceAdapterError as exc:
                self.observability.circuit_breaker.record_failure(adapter_id, fetch_method, exc.code)
                self.observability.record_fetch(
                    adapter_id=adapter_id,
                    fetch_method=fetch_method,
                    error_code=exc.code.value,
                    job_id=task.job_id,
                    task_id=task.id,
                )
                raise
            response_bytes = max(0, int(chapter.fetch_bytes_received or len(chapter.text.encode("utf-8"))))
            if response_bytes > self.max_chapter_bytes:
                self.observability.record_fetch(
                    adapter_id=chapter.adapter_id or adapter_id,
                    adapter_version=chapter.adapter_version,
                    fetch_method=chapter.fetch_method or fetch_method,
                    error_code=FetchErrorCode.CONTENT_INVALID.value,
                    elapsed_ms=chapter.fetch_elapsed_ms,
                    response_bytes=response_bytes,
                    job_id=task.job_id,
                    task_id=task.id,
                )
                raise SourceAdapterError(
                    "Chapter response exceeds the configured size limit",
                    code=FetchErrorCode.CONTENT_INVALID,
                    retryable=False,
                    http_status=413,
                )
            self.observability.circuit_breaker.record_success(chapter.adapter_id or adapter_id, chapter.fetch_method or fetch_method)
            self.observability.record_fetch(
                adapter_id=chapter.adapter_id or adapter_id,
                adapter_version=chapter.adapter_version,
                fetch_method=chapter.fetch_method or fetch_method,
                elapsed_ms=chapter.fetch_elapsed_ms,
                response_bytes=response_bytes,
                job_id=task.job_id,
                task_id=task.id,
            )
            with self._lock:
                self._chapters[task.id] = chapter
            return None
        if stage is TaskStage.PARSING:
            chapter = self._chapter(task.id)
            normalized = normalize_import_text(chapter.text)
            with self._lock:
                self._chapters[task.id] = replace(chapter, text=normalized)
            return None
        if stage is TaskStage.VALIDATING:
            if not self._chapter(task.id).text:
                self.release_task(task.id)
                raise SourceAdapterError(
                    "Chapter content is empty",
                    code=FetchErrorCode.CONTENT_INVALID,
                    retryable=False,
                    http_status=422,
                )
            return None
        if stage is not TaskStage.IMPORTING:
            return None

        chapter = self._chapter(task.id)
        job = self.repository.get_job_internal(task.job_id)
        if job is None:
            self.release_task(task.id)
            raise SourceAdapterError(
                "Import job no longer exists",
                code=FetchErrorCode.IMPORT_FAILED,
                retryable=False,
                http_status=404,
            )
        config = job.config_snapshot
        try:
            result = self.pipeline.import_from_text(
                title=str(config.get("title") or ""),
                chapter_number=task.chapter_number or chapter.chapter_number,
                chapter_title=task.title or chapter.title,
                text=chapter.text,
                source_type="url",
                source_url=chapter.source_url or task.canonical_chapter_url,
                author=str(config.get("author") or ""),
                book_source=str(config.get("source") or chapter.source),
                book_source_url=str(config.get("source_url") or job.source_url),
                adapter_id=chapter.adapter_id,
            )
        finally:
            self.release_task(task.id)
        return TaskImportOutcome(
            book_id=result.book_id,
            chapter_id=result.chapter_id,
            text_length=result.stored_text_length,
            content_hash=result.content_hash,
            fetch_method=chapter.fetch_method,
            elapsed_ms=chapter.fetch_elapsed_ms,
            operation=result.operation,
        )

    def release_task(self, task_id: int) -> None:
        with self._lock:
            self._chapters.pop(task_id, None)

    def _chapter(self, task_id: int) -> SourceChapterContent:
        with self._lock:
            chapter = self._chapters.get(task_id)
        if chapter is None:
            raise SourceAdapterError(
                "Fetched chapter state is unavailable",
                code=FetchErrorCode.INTERNAL_ERROR,
                retryable=False,
                http_status=500,
            )
        return chapter
