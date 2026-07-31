"""Shared construction for the API and the dedicated durable import worker."""

from __future__ import annotations

from pathlib import Path

from app.database.import_jobs import ImportJobRepository
from app.mobile_api.config import mobile_settings
from app.mobile_api.dependencies import get_db_path
from app.mobile_api.services.pipeline_service import PipelineService
from app.observability import CircuitBreakerConfig, Observability, default_observability
from app.services.import_job_quotas import ImportJobQuotaPolicy
from app.services.import_job_runtime import RetryPolicy
from app.services.import_job_service import ImportJobService
from app.services.source_import_task_pipeline import SourceImportTaskPipeline


def create_import_job_service(
    *,
    worker_id: str,
    pipeline: PipelineService | None = None,
    db_path: Path | None = None,
    observability: Observability | None = None,
) -> ImportJobService:
    """Create a process-local service over the shared durable SQLite store.

    The API and the worker deliberately share the same construction rules so
    retry, quota, circuit-breaker, and safe observability behavior cannot drift.
    The only process-specific value is ``worker_id``.
    """

    resolved_pipeline = pipeline or PipelineService()
    resolved_db_path = Path(db_path or getattr(resolved_pipeline, "db_path", get_db_path()))
    resolved_observability = observability or default_observability
    resolved_observability.configure_circuit_breaker(
        CircuitBreakerConfig(
            failure_threshold=mobile_settings.source_circuit_failure_threshold,
            window_seconds=mobile_settings.source_circuit_window_seconds,
            cooldown_seconds=mobile_settings.source_circuit_cooldown_seconds,
        )
    )
    repository = ImportJobRepository(resolved_db_path)
    return ImportJobService(
        repository,
        worker_id=worker_id,
        pipeline=SourceImportTaskPipeline(
            repository,
            resolved_pipeline,
            observability=resolved_observability,
            max_chapter_bytes=mobile_settings.import_job_max_bytes_per_chapter,
        ),
        retry_policy=RetryPolicy(max_attempts=mobile_settings.import_job_max_retries_per_task),
        quota_policy=ImportJobQuotaPolicy(
            max_chapters_per_job=mobile_settings.import_job_max_chapters,
            max_active_jobs_per_owner=mobile_settings.import_job_max_active_per_user,
            max_retries_per_task=mobile_settings.import_job_max_retries_per_task,
            max_bytes_per_chapter=mobile_settings.import_job_max_bytes_per_chapter,
            max_job_duration_seconds=mobile_settings.import_job_max_duration_seconds,
        ),
        observability=resolved_observability,
    )
