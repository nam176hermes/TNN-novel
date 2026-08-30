from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from requests import Response

from app.database.db import (
    add_book,
    add_chapter,
    get_connection,
    get_job_attempts,
    get_job_logs,
    get_mobile_job,
    list_operational_events,
    get_qa_report,
    init_db,
    request_cancel_mobile_job,
    update_chapter_paths,
)
from app.ingestion.source_adapters import SourceBlockedError
from app.ingestion.source_policies import SourcePolicy
from app.mobile_api.services import job_service as job_service_module
from app.mobile_api.routers import jobs as jobs_router
from app.mobile_api.services.job_service import JobService, JobTracker
from app.mobile_api.services.glossary_service import GlossaryService
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.qa_service import QAService
from app.services.tts.availability import TTSUnavailableError


def test_mobile_jobs_schema_has_durable_step_progress_columns(temp_db_path) -> None:
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(mobile_jobs)").fetchall()}

    assert {
        "state",
        "current_book_id",
        "current_chapter_id",
        "current_chunk_index",
        "total_chunks",
        "current_step",
        "provider",
        "model",
        "retry_count",
        "started_at",
        "completed_at",
        "failed_at",
        "cancel_requested",
        "last_safe_error",
        "internal_error_ref",
    }.issubset(columns)


def test_job_tracker_persists_step_progress_and_sanitized_logs(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [42], 1, {"provider_id": "gemini"})

    assert tracker.update_job(
        job.job_id,
        status="running",
        progress=0,
        current_book_id=7,
        current_chapter_id=42,
        current_chunk_index=2,
        total_chunks=5,
        current_step="TRANSLATING",
        provider="gemini",
        model="gemini-live",
        message="Translating chunk",
    )
    assert tracker.update_job(
        job.job_id,
        status="failed",
        error="provider crashed with api_key=secret-token\nTraceback: boom",
        message="Failed with /home/user/private/path",
    )

    loaded = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert loaded is not None
    snapshot = loaded.to_dict()
    assert snapshot["state"] == "FAILED"
    assert snapshot["current_step"] == "TRANSLATING"
    assert snapshot["current_book_id"] == 7
    assert snapshot["current_chapter_id"] == 42
    assert snapshot["current_chunk_index"] == 2
    assert snapshot["total_chunks"] == 5
    assert snapshot["provider"] == "gemini"
    assert snapshot["model"] == "gemini-live"
    assert snapshot["failed_at"]
    assert snapshot["last_safe_error"] == "Job failed. Check server logs."

    logs = get_job_logs(temp_db_path, job_id=job.job_id)
    assert [item["event_type"] for item in logs][:2] == ["state_transition", "state_transition"]
    joined = "\n".join(f"{item['message']} {item['details']}" for item in logs)
    assert "secret-token" not in joined
    assert "Traceback" not in joined
    assert "/home/user" not in joined
    events = list_operational_events(temp_db_path, limit=10, severities=())
    failure_event = next(event for event in events if event["event_type"] == "job_failure")
    assert failure_event["severity"] == "error"
    assert failure_event["job_id"] == job.job_id


def test_stale_completion_after_durable_cancel_keeps_cancellation_telemetry(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("daily", None, 1)
    assert tracker.update_job(job.job_id, status="running", message="Starting daily batch")
    assert request_cancel_mobile_job(temp_db_path, job_id=job.job_id)

    assert tracker.update_job(
        job.job_id,
        status="completed",
        message="Daily batch completed",
        last_safe_error="stale completion error",
        internal_error_ref="stale-completion-ref",
    )

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    cached = tracker.get_job(job.job_id)
    assert persisted is not None
    assert cached is not None
    for snapshot in (persisted.to_dict(), cached.to_dict()):
        assert snapshot["status"] == "cancelled"
        assert snapshot["state"] == "CANCELED"
        assert snapshot["message"] == "Job cancelled by user"
        assert snapshot["error"] == ""
        assert snapshot["last_safe_error"] == ""
        assert snapshot["internal_error_ref"] == ""

    transition = get_job_logs(temp_db_path, job_id=job.job_id)[0]
    assert transition["state"] == "CANCELED"
    assert transition["message"] == "Job cancelled by user"
    assert transition["details"]["to_status"] == "cancelled"
    assert not [
        event
        for event in list_operational_events(temp_db_path, limit=10, severities=())
        if event["event_type"] == "job_failure" and event["job_id"] == job.job_id
    ]


def test_stale_failure_after_durable_cancel_keeps_cancellation_telemetry(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("daily", None, 1)
    assert tracker.update_job(job.job_id, status="running", message="Starting daily batch")
    assert request_cancel_mobile_job(temp_db_path, job_id=job.job_id)

    assert tracker.update_job(
        job.job_id,
        status="failed",
        message="Daily job failed",
        error="provider failure",
        last_safe_error="stale failure error",
        internal_error_ref="stale-failure-ref",
    )

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    cached = tracker.get_job(job.job_id)
    assert persisted is not None
    assert cached is not None
    for snapshot in (persisted.to_dict(), cached.to_dict()):
        assert snapshot["status"] == "cancelled"
        assert snapshot["state"] == "CANCELED"
        assert snapshot["message"] == "Job cancelled by user"
        assert snapshot["error"] == ""
        assert snapshot["last_safe_error"] == ""
        assert snapshot["internal_error_ref"] == ""

    transition = get_job_logs(temp_db_path, job_id=job.job_id)[0]
    assert transition["state"] == "CANCELED"
    assert transition["message"] == "Job cancelled by user"
    assert transition["details"]["to_status"] == "cancelled"
    assert not [
        event
        for event in list_operational_events(temp_db_path, limit=10, severities=())
        if event["event_type"] == "job_failure" and event["job_id"] == job.job_id
    ]


def test_job_tracker_rejects_terminal_to_running_transition(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [42], 1)

    assert tracker.update_job(job.job_id, status="completed", progress=1)
    assert not tracker.update_job(job.job_id, status="running", progress=0)

    loaded = tracker.get_job(job.job_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.to_dict()["state"] == "COMPLETED"


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_database_backed_cancel_preserves_cached_terminal_job(
    terminal_status: str,
    temp_db_path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [42], 1)
    assert tracker.update_job(job.job_id, status="running", message="Translating")
    assert tracker.update_job(job.job_id, status=terminal_status, message=f"Job {terminal_status}")

    assert tracker.cancel_job(job.job_id) is True

    cached = tracker.jobs[job.job_id]
    durable = get_mobile_job(temp_db_path, job.job_id)
    assert durable is not None
    assert {
        "cached": (cached.status, cached.state, cached.cancel_requested, cached.message),
        "durable": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
            durable["message"],
        ),
    } == {
        "cached": (terminal_status, terminal_status.upper(), False, f"Job {terminal_status}"),
        "durable": (terminal_status, terminal_status.upper(), False, f"Job {terminal_status}"),
    }


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_database_backed_cancel_reconciles_stale_running_tracker_to_terminal_winner(
    terminal_status: str,
    temp_db_path,
) -> None:
    init_db(temp_db_path)
    owner = JobTracker(db_path=temp_db_path)
    job = owner.create_job("translate", [42], 1)
    assert owner.update_job(job.job_id, status="running", message="Translating")
    stale = JobTracker(db_path=temp_db_path)
    stale_running = stale.get_job(job.job_id)
    assert stale_running is not None
    assert stale_running.status == "running"
    assert owner.update_job(job.job_id, status=terminal_status, message=f"Job {terminal_status}")

    assert stale.cancel_job(job.job_id) is True

    owner_cached = owner.jobs[job.job_id]
    stale_cached = stale.jobs[job.job_id]
    durable = get_mobile_job(temp_db_path, job.job_id)
    assert durable is not None
    expected = (terminal_status, terminal_status.upper(), False, f"Job {terminal_status}")
    assert (
        owner_cached.status,
        owner_cached.state,
        owner_cached.cancel_requested,
        owner_cached.message,
    ) == expected
    assert (
        stale_cached.status,
        stale_cached.state,
        stale_cached.cancel_requested,
        stale_cached.message,
    ) == expected
    assert (
        durable["status"],
        durable["state"],
        durable["cancel_requested"],
        durable["message"],
    ) == expected


def test_job_cancel_requested_for_missing_in_memory_job() -> None:
    service = JobService(object(), tracker=JobTracker())  # type: ignore[arg-type]

    assert service._job_cancel_requested("missing-job")


@pytest.mark.parametrize("status", ["cancelled", "canceled"])
def test_job_cancel_requested_for_cached_terminal_status_without_flag(status: str) -> None:
    tracker = JobTracker()
    job = tracker.create_job("translate", [42], 1)
    assert tracker.update_job(job.job_id, status=status)
    assert job.cancel_requested is False
    service = JobService(object(), tracker=tracker)  # type: ignore[arg-type]

    assert service._job_cancel_requested(job.job_id)


@pytest.mark.asyncio
async def test_job_cancel_request_is_persisted_until_worker_exits(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path, heartbeat_interval_seconds=0.01)
    job = tracker.create_job("translate", [42], 1)

    async def slow_work() -> None:
        await asyncio.sleep(5)

    tracker.start_background_task(job.job_id, slow_work())
    for _ in range(20):
        loaded = tracker.get_job(job.job_id)
        if loaded and loaded.status == "running":
            break
        await asyncio.sleep(0.01)

    assert tracker.cancel_job(job.job_id)
    task = tracker._tasks.get(job.job_id)
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)

    loaded = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert loaded is not None
    snapshot = loaded.to_dict()
    assert snapshot["status"] == "cancelled"
    assert snapshot["state"] == "CANCELED"
    assert snapshot["cancel_requested"] is True


@pytest.mark.asyncio
async def test_daily_job_observes_durable_cancel_and_does_not_start_next_chapter(
    temp_db_path,
) -> None:
    translated: list[int] = []

    class DurableCancelPipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 2
            return [
                {"id": 101, "book_id": 1},
                {"id": 102, "book_id": 1},
            ]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            if len(translated) == 1:
                assert request_cancel_mobile_job(temp_db_path, job_id=str(kwargs["job_id"]))
            return "translated"

    tracker = JobTracker(db_path=temp_db_path)
    service = JobService(DurableCancelPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)

    await service._run_daily_job(job.job_id, 2)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert persisted is not None
    assert translated == [101]
    assert persisted.status == "cancelled"
    assert persisted.state == "CANCELED"


@pytest.mark.asyncio
async def test_daily_job_does_not_start_chapter_when_start_update_reconciles_cancellation(
    temp_db_path,
    monkeypatch,
) -> None:
    translated: list[int] = []

    class ChapterStartCancelPipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 2
            return [
                {"id": 501, "book_id": 1},
                {"id": 502, "book_id": 1},
            ]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            return "translated"

    tracker = JobTracker(db_path=temp_db_path)
    service = JobService(ChapterStartCancelPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)
    update_job = tracker.update_job
    cancellation_injected = False

    def cancel_before_second_chapter_start(job_id: str, **changes) -> bool:
        nonlocal cancellation_injected
        if changes.get("current_chapter_id") == 502:
            cancellation_injected = True
            assert request_cancel_mobile_job(temp_db_path, job_id=job_id)
        return update_job(job_id, **changes)

    monkeypatch.setattr(tracker, "update_job", cancel_before_second_chapter_start)

    await service._run_daily_job(job.job_id, 2)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    cached = service.get_job_status(job.job_id)
    assert persisted is not None
    assert cached is not None
    assert cancellation_injected is True
    assert translated == [501]
    assert persisted.status == cached["status"] == "cancelled"
    assert persisted.state == cached["state"] == "CANCELED"
    assert persisted.cancel_requested is cached["cancel_requested"] is True


@pytest.mark.asyncio
async def test_daily_job_keeps_durable_cancel_when_translation_raises(
    temp_db_path,
) -> None:
    translated: list[int] = []

    class DurableCancelFailurePipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 2
            return [
                {"id": 201, "book_id": 1},
                {"id": 202, "book_id": 1},
            ]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            assert request_cancel_mobile_job(temp_db_path, job_id=str(kwargs["job_id"]))
            raise RuntimeError("provider failure after cancellation")

    tracker = JobTracker(db_path=temp_db_path)
    service = JobService(DurableCancelFailurePipeline(), tracker=tracker)  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)

    await service._run_daily_job(job.job_id, 2)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert persisted is not None
    assert translated == [201]
    assert persisted.status == "cancelled"
    assert persisted.state == "CANCELED"


@pytest.mark.asyncio
async def test_daily_job_durable_cancel_during_pending_lookup_is_not_overwritten(
    temp_db_path,
) -> None:
    translated: list[int] = []

    class PendingLookupCancelPipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 1
            assert request_cancel_mobile_job(temp_db_path, job_id=job.job_id)
            return [{"id": 301, "book_id": 1}]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            return "translated"

    tracker = JobTracker(db_path=temp_db_path)
    service = JobService(PendingLookupCancelPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)

    await service._run_daily_job(job.job_id, 1)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    cached = service.get_job_status(job.job_id)
    assert persisted is not None
    assert cached is not None
    assert translated == []
    assert persisted.status == cached["status"] == "cancelled"
    assert persisted.state == cached["state"] == "CANCELED"


@pytest.mark.asyncio
async def test_daily_job_cancel_before_final_completion_write_stays_cancelled(
    temp_db_path,
    monkeypatch,
) -> None:
    translated: list[int] = []

    class FinalCompletionCancelPipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 1
            return [{"id": 401, "book_id": 1}]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            return "translated"

    tracker = JobTracker(db_path=temp_db_path)
    service = JobService(FinalCompletionCancelPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)
    update_job = tracker.update_job

    def request_cancel_before_completion(job_id: str, **kwargs) -> bool:
        if kwargs.get("status") == "completed":
            assert request_cancel_mobile_job(temp_db_path, job_id=job_id)
        return update_job(job_id, **kwargs)

    monkeypatch.setattr(tracker, "update_job", request_cancel_before_completion)

    await service._run_daily_job(job.job_id, 1)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    cached = service.get_job_status(job.job_id)
    assert persisted is not None
    assert cached is not None
    assert translated == [401]
    assert persisted.status == cached["status"] == "cancelled"
    assert persisted.state == cached["state"] == "CANCELED"


@pytest.mark.asyncio
async def test_start_translate_job_book_zero_does_not_target_all_books(
    temp_db_path,
    tmp_path,
) -> None:
    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    update_chapter_paths(temp_db_path, chapter_id, status="cleaned")
    service = JobService(pipeline)

    job_id = service.start_translate_job(book_id=0)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["target_ids"] == []


def test_job_router_services_share_tracker_between_requests() -> None:
    db_path = jobs_router.get_db_path()
    init_db(db_path)
    jobs_router._SHARED_JOB_TRACKER = None
    job_service_module._SHARED_TRACKERS.pop(str(db_path), None)
    try:
        first_service = jobs_router.get_job_service()
        job_id = first_service.start_translate_job(book_id=0)

        second_service = jobs_router.get_job_service()

        status = second_service.get_job_status(job_id)
        assert status is not None
        assert status["job_id"] == job_id
    finally:
        jobs_router._SHARED_JOB_TRACKER = None
        job_service_module._SHARED_TRACKERS.pop(str(db_path), None)


def test_job_tracker_persists_finished_jobs_between_instances(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10, 11], 2, {"provider_id": "gemini"})

    assert tracker.update_job(job.job_id, status="running", progress=1, message="Translating chapter 10")
    assert tracker.update_job(job.job_id, status="completed", progress=2, message="Done")

    restarted_tracker = JobTracker(db_path=temp_db_path)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.job_id == job.job_id
    assert loaded_job.job_type == "translate"
    assert loaded_job.status == "completed"
    assert loaded_job.progress == 2
    assert loaded_job.total == 2
    assert loaded_job.target_ids == [10, 11]
    assert loaded_job.params == {"provider_id": "gemini"}
    assert loaded_job.finished_at is not None
    assert restarted_tracker.list_jobs()[0].job_id == job.job_id


def test_start_book_tts_job_targets_translated_chapters_missing_audio(temp_db_path, tmp_path, monkeypatch) -> None:
    class RecordingTracker(JobTracker):
        def start_background_task(self, job_id, coro) -> None:  # type: ignore[no-untyped-def]
            coro.close()

    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    book_id = add_book(temp_db_path, "Book")
    missing_audio_id = add_chapter(temp_db_path, book_id, 1, "Needs audio")
    has_audio_id = add_chapter(temp_db_path, book_id, 2, "Has audio")
    untranslated_id = add_chapter(temp_db_path, book_id, 3, "Not translated")
    translated_path = tmp_path / "translated.txt"
    translated_path.write_text("Bản dịch.", encoding="utf-8")
    translated_audio_path = tmp_path / "translated-audio.txt"
    translated_audio_path.write_text("Bản dịch có audio.", encoding="utf-8")
    audio_path = tmp_path / "chapter-2.mp3"
    audio_path.write_bytes(b"audio")
    update_chapter_paths(temp_db_path, missing_audio_id, translated_text_path=translated_path, status="translated")
    update_chapter_paths(
        temp_db_path,
        has_audio_id,
        translated_text_path=translated_audio_path,
        audio_path=audio_path,
        status="audio_done",
    )
    update_chapter_paths(temp_db_path, untranslated_id, status="cleaned")
    service = JobService(pipeline, tracker=RecordingTracker())
    monkeypatch.setattr(job_service_module, "require_tts_runtime_available", lambda: None)

    job_id = service.start_tts_job(book_id=book_id, chapter_ids=[], limit=200)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["target_ids"] == [missing_audio_id]
    assert status["total"] == 1


def test_start_tts_job_rejects_before_tracker_creation(monkeypatch) -> None:
    class EmptyPipeline:
        def list_chapters(self, book_id=None):  # type: ignore[no-untyped-def]
            return []

    class RecordingTracker:
        def __init__(self) -> None:
            self.create_calls = 0

        def create_job(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.create_calls += 1
            return type("CreatedJob", (), {"job_id": "unexpected-job"})()

        def update_job(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return True

    tracker = RecordingTracker()
    service = JobService(EmptyPipeline(), tracker=tracker)

    def reject_unavailable_runtime() -> None:
        raise TTSUnavailableError("Local F5 TTS is unavailable: a CUDA GPU is required.")

    monkeypatch.setattr(job_service_module, "require_tts_runtime_available", reject_unavailable_runtime, raising=False)

    with pytest.raises(TTSUnavailableError):
        service.start_tts_job(book_id=1)

    assert tracker.create_calls == 0


def test_start_book_translate_job_targets_untranslated_chapters_with_source(
    temp_db_path,
    tmp_path,
) -> None:
    class RecordingTracker(JobTracker):
        def start_background_task(self, job_id, coro) -> None:  # type: ignore[no-untyped-def]
            coro.close()

    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    book_id = add_book(temp_db_path, "Book")

    raw_path = tmp_path / "raw.txt"
    raw_path.write_text("原文", encoding="utf-8")
    cleaned_path = tmp_path / "cleaned.txt"
    cleaned_path.write_text("清理后的原文", encoding="utf-8")
    translated_path = tmp_path / "translated.txt"
    translated_path.write_text("Bản dịch tốt.", encoding="utf-8")

    raw_id = add_chapter(temp_db_path, book_id, 1, "Raw")
    cleaned_id = add_chapter(temp_db_path, book_id, 2, "Cleaned")
    translated_id = add_chapter(temp_db_path, book_id, 3, "Translated")
    missing_source_id = add_chapter(temp_db_path, book_id, 4, "Missing source")

    update_chapter_paths(temp_db_path, raw_id, raw_text_path=raw_path, status="raw")
    update_chapter_paths(temp_db_path, cleaned_id, cleaned_text_path=cleaned_path, status="cleaned")
    update_chapter_paths(
        temp_db_path,
        translated_id,
        raw_text_path=raw_path,
        translated_text_path=translated_path,
        status="translated",
    )
    update_chapter_paths(temp_db_path, missing_source_id, raw_text_path=tmp_path / "missing.txt", status="cleaned")

    service = JobService(pipeline, tracker=RecordingTracker())

    job_id = service.start_translate_job(book_id=book_id, chapter_ids=[], limit=10, preset_id="balanced")

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["target_ids"] == [raw_id, cleaned_id]
    assert status["total"] == 2


def test_job_tracker_marks_unfinished_jobs_failed_after_restart(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("daily", [], 100)
    assert tracker.update_job(job.job_id, status="running", progress=25, message="Running batch")
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE mobile_jobs SET updated_at = ? WHERE job_id = ?", (stale_at, job.job_id))
        conn.commit()

    restarted_tracker = JobTracker(db_path=temp_db_path)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "interrupted"
    assert loaded_job.progress == 25
    assert loaded_job.message == "Job interrupted before completion. Please retry the job."
    assert loaded_job.error == "Job interrupted before completion"
    assert loaded_job.finished_at is not None


def test_job_tracker_marks_queued_jobs_interrupted_after_restart(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE mobile_jobs SET updated_at = ?, created_at = ? WHERE job_id = ?", (stale_at, stale_at, job.job_id))
        conn.commit()

    restarted_tracker = JobTracker(db_path=temp_db_path)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "interrupted"
    assert loaded_job.message == "Job interrupted before completion. Please retry the job."
    assert loaded_job.error == "Job interrupted before completion"
    assert loaded_job.finished_at is not None


def test_job_tracker_keeps_fresh_queued_jobs_available_for_claim(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})

    second_tracker = JobTracker(db_path=temp_db_path)
    loaded_job = second_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "queued"
    assert loaded_job.finished_at is None


def test_shared_job_tracker_uses_configured_stale_and_heartbeat_thresholds(
    temp_db_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    monkeypatch.setattr(job_service_module.mobile_settings, "job_stale_after_seconds", 42, raising=False)
    monkeypatch.setattr(job_service_module.mobile_settings, "job_heartbeat_interval_seconds", 0.25, raising=False)
    job_service_module._SHARED_TRACKERS.pop(str(temp_db_path), None)

    tracker = job_service_module.get_shared_job_tracker(temp_db_path)

    assert tracker.stale_after_seconds == 42
    assert tracker.heartbeat_interval_seconds == 0.25
    job_service_module._SHARED_TRACKERS.pop(str(temp_db_path), None)


def test_job_tracker_recovers_stale_running_job_from_expired_lease(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'running',
                lease_token = 'stale-token',
                lease_owner = 'old-worker',
                heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (stale_at, stale_at, stale_at, job.job_id),
        )
        conn.commit()

    restarted_tracker = JobTracker(db_path=temp_db_path)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "interrupted"
    assert loaded_job.error == "Job interrupted before completion"
    with get_connection(temp_db_path) as conn:
        row = conn.execute("SELECT lease_token, lease_owner FROM mobile_jobs WHERE job_id = ?", (job.job_id,)).fetchone()
    assert row["lease_token"] == ""
    assert row["lease_owner"] == ""


def test_job_tracker_does_not_interrupt_fresh_running_job_with_valid_heartbeat(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    fresh_at = datetime.now(timezone.utc).isoformat()
    future_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'running',
                state = 'TRANSLATING',
                lease_token = 'fresh-token',
                lease_owner = 'worker',
                heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (fresh_at, future_at, fresh_at, job.job_id),
        )
        conn.commit()

    restarted_tracker = JobTracker(db_path=temp_db_path, stale_after_seconds=30)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "running"
    assert loaded_job.state == "TRANSLATING"


def test_job_tracker_does_not_interrupt_stale_terminal_job(temp_db_path) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    job = tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    tracker.update_job(job.job_id, status="completed", progress=1, message="Done")
    stale_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE mobile_jobs SET updated_at = ? WHERE job_id = ?", (stale_at, job.job_id))
        conn.commit()

    restarted_tracker = JobTracker(db_path=temp_db_path, stale_after_seconds=30)
    loaded_job = restarted_tracker.get_job(job.job_id)

    assert loaded_job is not None
    assert loaded_job.status == "completed"
    assert loaded_job.state == "COMPLETED"


@pytest.mark.asyncio
async def test_job_tracker_prevents_duplicate_background_claims(temp_db_path) -> None:
    init_db(temp_db_path)
    first_tracker = JobTracker(db_path=temp_db_path, heartbeat_interval_seconds=0.01)
    second_tracker = JobTracker(db_path=temp_db_path, heartbeat_interval_seconds=0.01)
    job = first_tracker.create_job("translate", [10], 1, {"provider_id": "gemini"})
    ran: list[str] = []

    async def work(label: str) -> None:
        ran.append(label)
        await asyncio.sleep(0.03)

    first_tracker.start_background_task(job.job_id, work("first"))
    second_tracker.start_background_task(job.job_id, work("second"))

    for _ in range(20):
        loaded = first_tracker.get_job(job.job_id)
        if loaded and loaded.status == "completed":
            break
        await asyncio.sleep(0.01)

    assert ran == ["first"]
    loaded = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert loaded is not None
    assert loaded.status == "completed"


def test_retry_failed_translation_job_after_restart_reuses_params_and_skips_completed_chapters(
    temp_db_path,
    tmp_path,
) -> None:
    class RecordingTracker(JobTracker):
        def start_background_task(self, job_id, coro) -> None:  # type: ignore[no-untyped-def]
            coro.close()

    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    book_id = add_book(temp_db_path, "Book")
    completed_id = add_chapter(temp_db_path, book_id, 1, "Completed")
    incomplete_id = add_chapter(temp_db_path, book_id, 2, "Incomplete")
    translated_path = tmp_path / "translated.txt"
    translated_path.write_text("Bản dịch tốt.", encoding="utf-8")
    update_chapter_paths(temp_db_path, completed_id, translated_text_path=translated_path, status="translated")
    update_chapter_paths(temp_db_path, incomplete_id, status="cleaned")

    tracker = JobTracker(db_path=temp_db_path)
    failed_job = tracker.create_job(
        "translate",
        [completed_id, incomplete_id],
        2,
        {
            "provider_id": "gemini",
            "model": "gemini-live",
            "host": "https://example.test/v1",
            "style_profile_id": "kiem_hiep",
            "preset_id": "balanced",
            "chunk_size": 3500,
        },
    )
    tracker.update_job(failed_job.job_id, status="running", progress=1, message="Translating")
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE mobile_jobs SET updated_at = ? WHERE job_id = ?", (stale_at, failed_job.job_id))
        conn.commit()

    restarted_tracker = RecordingTracker(db_path=temp_db_path)
    service = JobService(pipeline, tracker=restarted_tracker)

    retry_job_id = service.retry_failed_translation_job(failed_job.job_id)

    retry_status = service.get_job_status(retry_job_id)
    assert retry_status is not None
    assert retry_status["job_type"] == "translate"
    assert retry_status["target_ids"] == [incomplete_id]
    assert retry_status["retry_of_job_id"] == failed_job.job_id
    assert retry_status["retry_count"] == 1
    assert retry_status["previous_error"] == "Job interrupted before completion"
    assert retry_status["skipped_completed_chapter_ids"] == [completed_id]
    assert retry_status["preset_id"] == "balanced"
    assert retry_status["chunk_size"] == 3500

    original_status = service.get_job_status(failed_job.job_id)
    assert original_status is not None
    assert original_status["status"] == "interrupted"
    assert original_status["error"] == "Job interrupted before completion"
    assert original_status["retry_count"] == 1
    assert original_status["last_retry_job_id"] == retry_job_id


def test_retry_failed_translation_job_accepts_interrupted_jobs(temp_db_path, tmp_path) -> None:
    class RecordingTracker(JobTracker):
        def start_background_task(self, job_id, coro) -> None:  # type: ignore[no-untyped-def]
            coro.close()

    init_db(temp_db_path)
    pipeline = object.__new__(PipelineService)
    pipeline.db_path = temp_db_path
    pipeline.data_dir = tmp_path
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Interrupted")
    update_chapter_paths(temp_db_path, chapter_id, status="cleaned")

    tracker = RecordingTracker(db_path=temp_db_path)
    interrupted = tracker.create_job("translate", [chapter_id], 1, {"provider_id": "gemini"})
    tracker.update_job(
        interrupted.job_id,
        status="interrupted",
        message="Job interrupted before completion. Please retry the job.",
        error="Job interrupted before completion",
    )
    service = JobService(pipeline, tracker=tracker)

    retry_job_id = service.retry_failed_translation_job(interrupted.job_id)

    retry_status = service.get_job_status(retry_job_id)
    assert retry_status is not None
    assert retry_status["target_ids"] == [chapter_id]
    assert retry_status["retry_of_job_id"] == interrupted.job_id
    assert retry_status["retry_count"] == 1
    assert retry_status["previous_error"] == "Job interrupted before completion"


@pytest.mark.asyncio
async def test_translate_worker_failure_marks_job_failed(temp_db_path, caplog: pytest.LogCaptureFixture) -> None:
    class FailingPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> None:
            raise RuntimeError("provider rejected request with provider-secret")

    service = JobService(FailingPipeline())  # type: ignore[arg-type]
    with caplog.at_level("ERROR"):
        job_id = service.start_translate_job(chapter_ids=[10], provider_id="gemini", model="gemini-live")

        for _ in range(20):
            status = service.get_job_status(job_id)
            if status and status["status"] in {"failed", "completed"}:
                break
            await asyncio.sleep(0.01)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "failed"
    assert status["message"] == "Translation failed on chapter 10. Check provider settings and server logs."
    assert status["error"] == "Translation failed. Check provider settings and server logs."
    assert "provider-secret" not in status["message"]
    attempts = get_job_attempts(temp_db_path, job_id=job_id)
    assert len(attempts) == 1
    assert attempts[0]["chapter_id"] == 10
    assert attempts[0]["provider_id"] == "gemini"
    assert attempts[0]["model"] == "gemini-live"
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error"] == "provider rejected request with provider-secret"
    assert "provider rejected request with provider-secret" in caplog.text


@pytest.mark.asyncio
async def test_translate_worker_does_not_block_event_loop_during_slow_provider_call(temp_db_path) -> None:
    class SlowPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> str:
            time.sleep(0.2)
            return "translated slowly"

    service = JobService(SlowPipeline())  # type: ignore[arg-type]
    job_id = service.start_translate_job(chapter_ids=[10], provider_id="gemini", model="gemini-live")

    started = time.monotonic()
    await asyncio.sleep(0.02)
    elapsed = time.monotonic() - started

    status = service.get_job_status(job_id)
    assert elapsed < 0.12
    assert status is not None
    assert status["job_id"] == job_id
    assert status["progress"] == 0

    task = service.tracker._tasks[job_id]
    await task
    final_status = service.get_job_status(job_id)
    assert final_status is not None
    assert final_status["status"] == "completed"


@pytest.mark.asyncio
async def test_translate_worker_retries_transient_provider_503(temp_db_path, monkeypatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    response = Response()
    response.status_code = 503
    response.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    transient_error = requests.HTTPError(
        "503 Server Error: Service Unavailable for url: "
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        response=response,
    )

    class FlakyPipeline:
        db_path = temp_db_path
        calls = 0

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> str:
            self.calls += 1
            if self.calls == 1:
                raise transient_error
            return "translated after retry"

    pipeline = FlakyPipeline()
    service = JobService(pipeline)  # type: ignore[arg-type]
    job_id = service.start_translate_job(chapter_ids=[19], provider_id="gemini", model="gemini-live")

    task = service.tracker._tasks[job_id]
    await task

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert pipeline.calls == 2
    assert sleeps == [5.0]


@pytest.mark.asyncio
async def test_translate_worker_passes_cancel_check_and_stays_cancelled_mid_provider_call(temp_db_path) -> None:
    started = threading.Event()

    class CancelAwarePipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> str:
            cancel_check = kwargs["cancel_check"]
            started.set()
            while not cancel_check():
                time.sleep(0.005)
            raise RuntimeError("provider call observed cancel")

    service = JobService(CancelAwarePipeline())  # type: ignore[arg-type]
    job_id = service.start_translate_job(chapter_ids=[10], provider_id="gemini", model="gemini-live")

    for _ in range(50):
        if started.is_set():
            break
        await asyncio.sleep(0.01)

    assert started.is_set()
    assert service.cancel_job(job_id)
    await asyncio.gather(service.tracker._tasks[job_id], return_exceptions=True)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "cancelled"
    assert status["state"] == "CANCELED"
    assert status["message"] == "Job cancelled"


@pytest.mark.asyncio
async def test_translate_worker_passes_style_profile_id_to_pipeline(temp_db_path) -> None:
    captured: dict[str, object] = {}

    class RecordingPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> str:
            captured.update(kwargs)
            return "translated"

    service = JobService(RecordingPipeline())  # type: ignore[arg-type]
    job_id = service.start_translate_job(
        chapter_ids=[10],
        provider_id="deepseek",
        model="deepseek-live",
        style_profile_id="kiem_hiep",
    )

    for _ in range(20):
        status = service.get_job_status(job_id)
        if status and status["status"] in {"failed", "completed"}:
            break
        await asyncio.sleep(0.01)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert captured["style_profile_id"] == "kiem_hiep"
    attempts = get_job_attempts(temp_db_path, job_id=job_id)
    assert len(attempts) == 1
    assert attempts[0]["chapter_id"] == 10
    assert attempts[0]["provider_id"] == "deepseek"
    assert attempts[0]["model"] == "deepseek-live"
    assert attempts[0]["status"] == "success"
    assert attempts[0]["error"] == ""


@pytest.mark.asyncio
async def test_successful_translation_records_bounded_sanitized_glossary_warnings(
    temp_db_path,
    tmp_path,
    monkeypatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")
    translated_path = tmp_path / "translated.txt"

    class SavingPipeline:
        db_path = temp_db_path

        def get_chapter(self, target_chapter_id: int) -> dict:
            return {"id": target_chapter_id, "book_id": book_id}

        def translate_chapter(self, **_kwargs) -> str:
            translated_path.write_text("Bản dịch đã lưu.", encoding="utf-8")
            update_chapter_paths(
                temp_db_path,
                chapter_id,
                translated_text_path=translated_path,
                status="translated",
            )
            return "Bản dịch đã lưu."

    warnings = [
        {"code": "provider_unavailable", "message": "Hybrid glossary extraction was skipped."}
        for _ in range(12)
    ] + [{"code": "unknown", "message": "provider-secret /private/prompt"}]
    monkeypatch.setattr(
        GlossaryService,
        "extract_chapter_terms",
        lambda *args, **kwargs: {"created": 0, "updated": 0, "warnings": warnings},
    )
    monkeypatch.setattr(
        QAService,
        "run_deterministic_qa",
        lambda *args, **kwargs: {"overall_status": "PASS", "issues": []},
    )
    service = JobService(SavingPipeline())  # type: ignore[arg-type]

    job_id = service.start_translate_job(
        chapter_ids=[chapter_id],
        provider_id="fake",
        model="fake-model",
    )
    await service.tracker._tasks[job_id]

    status = service.get_job_status(job_id)
    logs = get_job_logs(temp_db_path, job_id=job_id)
    qa_completed = next(log for log in logs if log["event_type"] == "qa_completed")
    details = qa_completed["details"]
    assert status is not None
    assert status["status"] == "completed"
    assert translated_path.read_text(encoding="utf-8") == "Bản dịch đã lưu."
    assert details["glossary_warning_count"] == 13
    assert details["glossary_warnings_truncated"] is True
    assert len(details["glossary_warning_codes"].split(",")) == 10
    assert details["glossary_warning_codes"].split(",")[0] == "provider_unavailable"
    assert details["glossary_warning_messages"].split(" | ")[0] == (
        "Hybrid glossary extraction was skipped."
    )
    assert "provider-secret" not in json.dumps(details)
    assert "/private/prompt" not in json.dumps(details)


@pytest.mark.asyncio
async def test_translate_worker_uses_preset_pipeline_when_preset_id_is_supplied(temp_db_path) -> None:
    captured: dict[str, object] = {}

    class PresetPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter(self, **kwargs) -> str:
            raise AssertionError("single-step translate should not be used for preset jobs")

        def translate_chapter_with_pipeline(self, **kwargs) -> dict:
            captured.update(kwargs)
            return {"text": "polished", "qa_report": {"quality_score": 9}}

    service = JobService(PresetPipeline())  # type: ignore[arg-type]
    job_id = service.start_translate_job(
        chapter_ids=[10],
        preset_id="balanced",
        style_profile_id="tien_hiep",
    )

    for _ in range(20):
        status = service.get_job_status(job_id)
        if status and status["status"] in {"failed", "completed"}:
            break
        await asyncio.sleep(0.01)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert captured["preset_id"] == "balanced"
    assert captured["style_profile_id"] == "tien_hiep"
    assert captured["chapter_id"] == 10


@pytest.mark.asyncio
async def test_translate_worker_passes_fast_draft_chunk_size_to_pipeline(temp_db_path) -> None:
    captured: dict[str, object] = {}

    class PresetPipeline:
        db_path = temp_db_path

        def get_chapter(self, chapter_id: int) -> dict:
            return {"id": chapter_id, "book_id": 1}

        def translate_chapter_with_pipeline(self, **kwargs) -> dict:
            captured.update(kwargs)
            return {"text": "draft", "qa_report": None}

    service = JobService(PresetPipeline())  # type: ignore[arg-type]
    job_id = service.start_translate_job(
        chapter_ids=[10],
        preset_id="fast_draft",
        style_profile_id="huyen_huyen",
    )

    task = service.tracker._tasks[job_id]
    await task

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["preset_id"] == "fast_draft"
    assert status["chunk_size"] == 3500
    assert captured["chunk_size"] == 3500


@pytest.mark.asyncio
async def test_qa_worker_persists_report(
    temp_db_path,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Book")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter")

    class QaPipeline:
        db_path = temp_db_path

        def get_chapter(self, target_chapter_id: int) -> dict:
            return {"id": target_chapter_id, "book_id": book_id}

        def run_qa_check(self, **kwargs) -> dict:
            return {
                "quality_score": 8.5,
                "fidelity_score": 9,
                "style_score": 8,
                "glossary_score": 8,
                "audiobook_score": 9,
                "verdict": "PASS",
                "issues": [{"type": "style", "message": "Tighten phrasing"}],
            }

    service = JobService(QaPipeline())  # type: ignore[arg-type]
    job_id = service.start_qa_job(chapter_ids=[chapter_id], provider_id="gemini", model="gemini-qa")

    for _ in range(20):
        status = service.get_job_status(job_id)
        if status and status["status"] in {"failed", "completed"}:
            break
        await asyncio.sleep(0.01)

    status = service.get_job_status(job_id)
    report = get_qa_report(temp_db_path, book_id, chapter_id)

    assert status is not None
    assert status["status"] == "completed"
    assert report is not None
    assert report["quality_score"] == 8.5
    assert report["verdict"] == "PASS"
    attempts = get_job_attempts(temp_db_path, job_id=job_id)
    assert len(attempts) == 1
    assert attempts[0]["chapter_id"] == chapter_id
    assert attempts[0]["provider_id"] == "gemini"
    assert attempts[0]["model"] == "gemini-qa"
    assert attempts[0]["status"] == "success"


@pytest.mark.asyncio
async def test_import_url_worker_imports_selected_chapters_with_progress(temp_db_path, monkeypatch) -> None:
    init_db(temp_db_path)
    imported: list[dict] = []
    monkeypatch.setattr(
        "app.mobile_api.services.job_service.get_source_policy",
        lambda url: SourcePolicy("69shuba", "69shuba", ("69shuba.com",), delay_seconds=0),
    )

    class ImportPipeline:
        db_path = temp_db_path

        def import_from_source_url(self, **kwargs) -> dict:
            imported.append(kwargs)
            return {"chapter_id": 100 + len(imported)}

    service = JobService(ImportPipeline())  # type: ignore[arg-type]
    job_id = service.start_import_url_job(
        url="https://www.69shuba.com/book/1",
        title="凡人修仙传",
        author="忘语",
        source="www.69shuba.com",
        chapters=[
            {
                "url": "https://www.69shuba.com/book/1/chapter/1",
                "chapter_number": 1,
                "title": "第一章 山边小村",
            },
            {
                "url": "https://www.69shuba.com/book/1/chapter/2",
                "chapter_number": 2,
                "title": "第二章 青牛镇",
            },
        ],
    )

    for _ in range(20):
        status = service.get_job_status(job_id)
        if status and status["status"] in {"failed", "completed"}:
            break
        await asyncio.sleep(0.01)

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert status["progress"] == 2
    assert status["total"] == 2
    assert status["message"] == "Imported 2 chapters"
    assert [item["chapter_number"] for item in imported] == [1, 2]
    assert imported[0]["book_title"] == "凡人修仙传"
    assert imported[0]["source_url"] == "https://www.69shuba.com/book/1"


@pytest.mark.asyncio
async def test_import_url_worker_waits_between_policy_source_chapters(monkeypatch) -> None:
    sleeps: list[float] = []
    imported: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class ImportPipeline:
        db_path = None

        def import_from_source_url(self, **kwargs) -> dict:
            imported.append(kwargs)
            return {"chapter_id": 100 + len(imported)}

    tracker = JobTracker()
    service = JobService(ImportPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job_id = service.start_import_url_job(
        url="https://www.69shuba.com/book/1/",
        title="凡人修仙传",
        author="忘语",
        source="69shuba",
        chapters=[
            {
                "url": "https://www.69shuba.com/book/1/1.html",
                "chapter_number": 1,
                "title": "第1章 山边小村",
            },
            {
                "url": "https://www.69shuba.com/book/1/2.html",
                "chapter_number": 2,
                "title": "第2章 青牛镇",
            },
        ],
    )

    task = tracker._tasks[job_id]
    await task

    assert [item["chapter_number"] for item in imported] == [1, 2]
    assert sleeps == [8]


@pytest.mark.asyncio
async def test_import_url_worker_offloads_blocking_source_import(monkeypatch) -> None:
    offloaded_calls = 0

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal offloaded_calls
        offloaded_calls += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    class ImportPipeline:
        db_path = None

        def import_from_source_url(self, **kwargs) -> dict:
            return {"chapter_id": 101}

    tracker = JobTracker()
    service = JobService(ImportPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job_id = service.start_import_url_job(
        url="https://www.69shuba.com/book/1/",
        title="凡人修仙传",
        author="忘语",
        source="69shuba",
        chapters=[
            {
                "url": "https://www.69shuba.com/book/1/1.html",
                "chapter_number": 1,
                "title": "第1章 山边小村",
            }
        ],
    )

    task = tracker._tasks[job_id]
    await task

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "completed"
    assert offloaded_calls == 1


@pytest.mark.asyncio
async def test_import_url_worker_stops_on_source_block_without_retrying_or_continuing() -> None:
    imported_numbers: list[int] = []

    class ImportPipeline:
        db_path = None

        def import_from_source_url(self, **kwargs) -> dict:
            chapter_number = int(kwargs["chapter_number"])
            imported_numbers.append(chapter_number)
            if chapter_number == 2:
                raise SourceBlockedError("Source cooldown or captcha page detected")
            return {"chapter_id": 100 + chapter_number}

    tracker = JobTracker()
    service = JobService(ImportPipeline(), tracker=tracker)  # type: ignore[arg-type]
    job_id = service.start_import_url_job(
        url="https://www.69shuba.com/book/1/",
        title="凡人修仙传",
        author="忘语",
        source="69shuba",
        chapters=[
            {
                "url": "https://www.69shuba.com/book/1/1.html",
                "chapter_number": 1,
                "title": "第1章 山边小村",
            },
            {
                "url": "https://www.69shuba.com/book/1/2.html",
                "chapter_number": 2,
                "title": "第2章 青牛镇",
            },
            {
                "url": "https://www.69shuba.com/book/1/3.html",
                "chapter_number": 3,
                "title": "第3章 七玄门",
            },
        ],
        retry_limit=2,
    )

    task = tracker._tasks[job_id]
    await task

    status = service.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "failed"
    assert status["progress"] == 1
    assert status["message"] == "Source blocked; import stopped"
    assert "cooldown" in status["error"]
    assert imported_numbers == [1, 2]
