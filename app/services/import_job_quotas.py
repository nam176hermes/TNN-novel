"""Server-side import-job quotas shared by API and worker code."""

from __future__ import annotations

from dataclasses import dataclass


class ImportJobQuotaError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ImportJobQuotaPolicy:
    max_chapters_per_job: int = 200
    max_active_jobs_per_owner: int = 4
    max_retries_per_task: int = 3
    max_bytes_per_chapter: int = 5 * 1024 * 1024
    max_job_duration_seconds: int = 60 * 60

    def __post_init__(self) -> None:
        for field_name, value in (
            ("max_chapters_per_job", self.max_chapters_per_job),
            ("max_active_jobs_per_owner", self.max_active_jobs_per_owner),
            ("max_retries_per_task", self.max_retries_per_task),
            ("max_bytes_per_chapter", self.max_bytes_per_chapter),
            ("max_job_duration_seconds", self.max_job_duration_seconds),
        ):
            if int(value) <= 0:
                raise ValueError(f"{field_name} must be positive")
