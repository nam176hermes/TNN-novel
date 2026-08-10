from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier

import pytest

import app.database.import_jobs as import_jobs
from app.database.db import init_db
from app.database.import_jobs import ImportJob, ImportJobRepository, JobStatus, TaskStage, TaskStatus
from app.import_contracts import (
    BrowserResultState,
    BrowserTaskResult,
    ImportOperationKind,
    PreviewBrowserPayload,
    encode_browser_result,
)


OWNER = "operator-a"
WORKER = "browser-worker-a"
CORRELATION_ID = "preview-correlation"
FUTURE_DEADLINE = "2099-08-10T12:00:00+00:00"
EXPIRED_DEADLINE = "2000-08-10T12:00:00+00:00"


@dataclass(frozen=True)
class ActivePreview:
    repository: ImportJobRepository
    job: ImportJob
    task_id: int
    task_version: int
    lease_token: str
    lease_owner: str


def _active_preview(temp_db_path, *, deadline_at: str = FUTURE_DEADLINE) -> ActivePreview:
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    job = repository.create_job(
        owner_user_id=OWNER,
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        operation_kind=ImportOperationKind.PREVIEW,
        deadline_at=deadline_at,
        correlation_id=CORRELATION_ID,
    )
    task = repository.create_task(
        job_id=job.id,
        owner_user_id=OWNER,
        canonical_identity="69shuba:https://www.69shuba.com/book/123",
        canonical_chapter_url="https://www.69shuba.com/book/123",
        chapter_number=0,
        title="Preview",
    )
    running_job = repository.transition_job(job.id, OWNER, JobStatus.RUNNING)
    claimed = repository.claim_next_task(job.id, OWNER, worker_id=WORKER)
    assert claimed is not None
    assert claimed.id == task.id
    return ActivePreview(
        repository=repository,
        job=running_job,
        task_id=claimed.id,
        task_version=claimed.version,
        lease_token=claimed.lease_token,
        lease_owner=claimed.lease_owner,
    )


def _completed_result(*, title: str = "A novel", correlation_id: str = CORRELATION_ID):
    return BrowserTaskResult(
        correlation_id=correlation_id,
        state=BrowserResultState.COMPLETED,
        payload=PreviewBrowserPayload(
            adapter_id="69shuba",
            adapter_label="69shu-ba",
            source="69shuba",
            source_url="https://www.69shuba.com/book/123",
            title=title,
        ),
    )


def _publish(active: ActivePreview, result: BrowserTaskResult) -> ImportJob:
    return active.repository.publish_browser_result(
        active.job.id,
        OWNER,
        task_id=active.task_id,
        lease_token=active.lease_token,
        lease_owner=active.lease_owner,
        expected_job_version=active.job.version,
        expected_task_version=active.task_version,
        result=result,
    )


def test_active_lease_atomically_publishes_preview_result_and_terminal_events(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    result = _completed_result()

    published = _publish(active, result)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)

    assert published.result_snapshot == result
    assert published.result_state is BrowserResultState.COMPLETED
    assert published.result_published_at
    assert published.status is JobStatus.SUCCEEDED
    assert published.finished_at
    assert task.status is TaskStatus.SUCCEEDED
    assert task.stage is TaskStage.SUCCEEDED
    assert task.finished_at
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert [event.event_type for event in events[-3:]] == [
        "browser_result_published",
        "task_transitioned",
        "job_transitioned",
    ]
    assert events[-3].payload == {
        "correlation_id": CORRELATION_ID,
        "error_code": "",
        "state": "COMPLETED",
    }
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert "A novel" not in json.dumps([event.payload for event in events])


@pytest.mark.parametrize(
    ("result_state", "error_code", "expected_task_status", "expected_job_status"),
    [
        (
            BrowserResultState.BLOCKED,
            "user_verification_required",
            TaskStatus.USER_VERIFICATION_REQUIRED,
            JobStatus.FAILED,
        ),
        (BrowserResultState.FAILED, "browser_failed", TaskStatus.FAILED, JobStatus.FAILED),
        (BrowserResultState.CANCELLED, "cancelled", TaskStatus.CANCELLED, JobStatus.CANCELLED),
        (BrowserResultState.TIMED_OUT, "browser_task_timed_out", TaskStatus.FAILED, JobStatus.FAILED),
    ],
)
def test_browser_result_states_map_to_terminal_job_and_task_rows(
    temp_db_path,
    result_state,
    error_code,
    expected_task_status,
    expected_job_status,
) -> None:
    active = _active_preview(temp_db_path)
    result = BrowserTaskResult(
        correlation_id=CORRELATION_ID,
        state=result_state,
        error_code=error_code,
        error_message="Safe browser result",
        retryable=False,
    )

    published = _publish(active, result)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]

    assert published.result_snapshot == result
    assert published.status is expected_job_status
    assert task.status is expected_task_status
    assert task.stage.value == expected_task_status.value
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")


def test_stale_lease_or_owner_cannot_publish_browser_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    result = _completed_result()
    events_before = active.repository.list_events(active.job.id, OWNER)

    for overrides in (
        {"lease_token": "stale-lease"},
        {"lease_owner": "browser-worker-b"},
    ):
        arguments = {
            "task_id": active.task_id,
            "lease_token": active.lease_token,
            "lease_owner": active.lease_owner,
            "expected_job_version": active.job.version,
            "expected_task_version": active.task_version,
            "result": result,
        }
        arguments.update(overrides)
        with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
            active.repository.publish_browser_result(active.job.id, OWNER, **arguments)
        assert rejected.value.code == "stale_lease"

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    assert current is not None and current.result_snapshot is None
    assert current.status is JobStatus.RUNNING
    assert task.status is TaskStatus.RUNNING
    assert task.lease_token == active.lease_token
    assert active.repository.list_events(active.job.id, OWNER) == events_before


def test_stale_job_or_task_version_cannot_publish_browser_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    result = _completed_result()
    events_before = active.repository.list_events(active.job.id, OWNER)

    for version_overrides in (
        {"expected_job_version": active.job.version - 1},
        {"expected_task_version": active.task_version - 1},
    ):
        arguments = {
            "task_id": active.task_id,
            "lease_token": active.lease_token,
            "lease_owner": active.lease_owner,
            "expected_job_version": active.job.version,
            "expected_task_version": active.task_version,
            "result": result,
        }
        arguments.update(version_overrides)
        with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
            active.repository.publish_browser_result(active.job.id, OWNER, **arguments)
        assert rejected.value.code == "stale_lease"

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    assert current is not None and current.result_snapshot is None
    assert task.status is TaskStatus.RUNNING
    assert active.repository.list_events(active.job.id, OWNER) == events_before


def test_cancel_requested_wins_over_late_completed_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)

    cancelled = active.repository.request_cancel(active.job.id, OWNER)
    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        _publish(active, _completed_result())

    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)
    assert rejected.value.code == "already_published"
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.result_state is BrowserResultState.CANCELLED
    assert cancelled.result_snapshot is not None
    assert cancelled.result_snapshot.error_code == "cancelled"
    assert cancelled.cancel_requested_at
    assert cancelled.finished_at
    assert task.status is TaskStatus.CANCELLED
    assert task.stage is TaskStage.CANCELLED
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert [event.event_type for event in events].count("browser_result_published") == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_expired_deadline_cannot_publish_completed_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path, deadline_at=EXPIRED_DEADLINE)
    events_before = active.repository.list_events(active.job.id, OWNER)

    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        _publish(active, _completed_result())

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    assert rejected.value.code == "deadline_exceeded"
    assert current is not None and current.result_snapshot is None
    assert current.status is JobStatus.RUNNING
    assert task.status is TaskStatus.RUNNING
    assert task.lease_token == active.lease_token
    assert active.repository.list_events(active.job.id, OWNER) == events_before


def test_expired_task_lease_cannot_publish_browser_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    with sqlite3.connect(temp_db_path) as connection:
        connection.execute(
            "UPDATE chapter_tasks SET lease_expires_at = ? WHERE id = ?",
            (EXPIRED_DEADLINE, active.task_id),
        )
    events_before = active.repository.list_events(active.job.id, OWNER)

    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        _publish(active, _completed_result())

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    assert rejected.value.code == "stale_lease"
    assert current is not None and current.result_snapshot is None
    assert current.status is JobStatus.RUNNING
    assert task.status is TaskStatus.RUNNING
    assert task.lease_token == active.lease_token
    assert task.lease_expires_at == EXPIRED_DEADLINE
    assert active.repository.list_events(active.job.id, OWNER) == events_before


def test_duplicate_identical_publication_is_idempotent_but_different_result_cannot_overwrite(
    temp_db_path,
) -> None:
    active = _active_preview(temp_db_path)
    result = _completed_result()
    first = _publish(active, result)
    first_events = active.repository.list_events(active.job.id, OWNER)

    duplicate = _publish(active, result)
    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        _publish(active, _completed_result(title="A different novel"))

    final_events = active.repository.list_events(active.job.id, OWNER)
    assert duplicate == first
    assert rejected.value.code == "already_published"
    assert duplicate.result_snapshot == result
    assert final_events == first_events
    assert [event.event_type for event in final_events].count("browser_result_published") == 1


def test_two_workers_can_publish_only_one_terminal_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    barrier = Barrier(2)
    results = [_completed_result(title="First result"), _completed_result(title="Second result")]

    def publish(repository: ImportJobRepository, result: BrowserTaskResult):
        barrier.wait(timeout=5)
        try:
            return repository.publish_browser_result(
                active.job.id,
                OWNER,
                task_id=active.task_id,
                lease_token=active.lease_token,
                lease_owner=active.lease_owner,
                expected_job_version=active.job.version,
                expected_task_version=active.task_version,
                result=result,
            )
        except import_jobs.BrowserResultPublicationRejected as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                publish,
                [ImportJobRepository(temp_db_path), ImportJobRepository(temp_db_path)],
                results,
            )
        )

    winners = [outcome for outcome in outcomes if isinstance(outcome, ImportJob)]
    losers = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, import_jobs.BrowserResultPublicationRejected)
    ]
    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)
    with sqlite3.connect(temp_db_path) as connection:
        stored_snapshot = connection.execute(
            "SELECT result_snapshot_json FROM import_jobs WHERE id = ?", (active.job.id,)
        ).fetchone()[0]

    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].code == "already_published"
    assert stored_snapshot in {encode_browser_result(result) for result in results}
    assert current is not None and current.status is JobStatus.SUCCEEDED
    assert current.result_snapshot in results
    assert task.status is TaskStatus.SUCCEEDED
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert [event.event_type for event in events].count("browser_result_published") == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_publication_race_with_cancellation_has_one_consistent_terminal_result(
    temp_db_path,
) -> None:
    active = _active_preview(temp_db_path)
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=5)
        try:
            return _publish(active, _completed_result())
        except import_jobs.BrowserResultPublicationRejected as exc:
            return exc

    def cancel():
        barrier.wait(timeout=5)
        return ImportJobRepository(temp_db_path).request_cancel(active.job.id, OWNER)

    with ThreadPoolExecutor(max_workers=2) as executor:
        publication = executor.submit(publish)
        cancellation = executor.submit(cancel)
        outcomes = [publication.result(), cancellation.result()]

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)
    assert current is not None
    assert current.result_state in {BrowserResultState.COMPLETED, BrowserResultState.CANCELLED}
    assert current.result_snapshot is not None
    assert current.status is (
        JobStatus.SUCCEEDED
        if current.result_state is BrowserResultState.COMPLETED
        else JobStatus.CANCELLED
    )
    assert task.status is (
        TaskStatus.SUCCEEDED
        if current.result_state is BrowserResultState.COMPLETED
        else TaskStatus.CANCELLED
    )
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert [event.event_type for event in events].count("browser_result_published") == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert any(isinstance(outcome, ImportJob) for outcome in outcomes)


def test_publication_race_with_timeout_has_one_consistent_terminal_result(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=5)
        try:
            return _publish(active, _completed_result())
        except import_jobs.BrowserResultPublicationRejected as exc:
            return exc

    def expire():
        barrier.wait(timeout=5)
        return ImportJobRepository(temp_db_path).expire_browser_job(active.job.id, OWNER)

    with ThreadPoolExecutor(max_workers=2) as executor:
        publication = executor.submit(publish)
        expiration = executor.submit(expire)
        outcomes = [publication.result(), expiration.result()]

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)
    event_types = [event.event_type for event in events]
    assert current is not None
    assert current.result_state in {BrowserResultState.COMPLETED, BrowserResultState.TIMED_OUT}
    assert current.result_snapshot is not None
    assert current.status is (
        JobStatus.SUCCEEDED
        if current.result_state is BrowserResultState.COMPLETED
        else JobStatus.FAILED
    )
    assert task.status is (
        TaskStatus.SUCCEEDED
        if current.result_state is BrowserResultState.COMPLETED
        else TaskStatus.FAILED
    )
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert event_types.count("browser_result_published") + event_types.count(
        "browser_job_timed_out"
    ) == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert any(isinstance(outcome, ImportJob) for outcome in outcomes)


def test_publication_rolls_back_task_update_when_job_update_fails(temp_db_path) -> None:
    active = _active_preview(temp_db_path)
    events_before = active.repository.list_events(active.job.id, OWNER)
    with sqlite3.connect(temp_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_browser_result_update
            BEFORE UPDATE OF result_state ON import_jobs
            WHEN NEW.result_state != ''
            BEGIN
                SELECT RAISE(ABORT, 'forced publication failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced publication failure"):
        _publish(active, _completed_result())

    current = active.repository.get_job(active.job.id, OWNER)
    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    assert current is not None and current.result_snapshot is None
    assert current.status is JobStatus.RUNNING
    assert task.status is TaskStatus.RUNNING
    assert task.stage is TaskStage.QUEUED
    assert task.lease_token == active.lease_token
    assert task.lease_owner == active.lease_owner
    assert task.version == active.task_version
    assert active.repository.list_events(active.job.id, OWNER) == events_before


def test_expire_browser_job_records_timeout_and_invalidates_running_lease(temp_db_path) -> None:
    active = _active_preview(temp_db_path, deadline_at=EXPIRED_DEADLINE)

    expired = active.repository.expire_browser_job(active.job.id, OWNER)
    duplicate = active.repository.expire_browser_job(active.job.id, OWNER)

    task = active.repository.list_tasks(active.job.id, OWNER)[0]
    events = active.repository.list_events(active.job.id, OWNER)
    assert duplicate == expired
    assert expired.status is JobStatus.FAILED
    assert expired.result_state is BrowserResultState.TIMED_OUT
    assert expired.result_snapshot is not None
    assert expired.result_snapshot.error_code == "browser_task_timed_out"
    assert expired.result_published_at
    assert expired.cancel_requested_at
    assert expired.finished_at
    assert task.status is TaskStatus.FAILED
    assert task.stage is TaskStage.FAILED
    assert task.error_code == "browser_task_timed_out"
    assert task.finished_at
    assert (task.lease_token, task.lease_owner, task.lease_expires_at) == ("", "", "")
    assert [event.event_type for event in events].count("browser_job_timed_out") == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_import_chapters_job_rejects_browser_result_publication(temp_db_path) -> None:
    init_db(temp_db_path)
    repository = ImportJobRepository(temp_db_path)
    job = repository.create_job(
        owner_user_id=OWNER,
        source="69shuba",
        source_url="https://www.69shuba.com/book/123",
        deadline_at=FUTURE_DEADLINE,
        correlation_id=CORRELATION_ID,
    )
    task = repository.create_task(
        job_id=job.id,
        owner_user_id=OWNER,
        canonical_identity="69shuba:https://www.69shuba.com/chapter/1",
        canonical_chapter_url="https://www.69shuba.com/chapter/1",
        chapter_number=1,
        title="Chapter 1",
    )
    running = repository.transition_job(job.id, OWNER, JobStatus.RUNNING)
    claimed = repository.claim_next_task(job.id, OWNER, worker_id=WORKER)
    assert claimed is not None and claimed.id == task.id

    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        repository.publish_browser_result(
            job.id,
            OWNER,
            task_id=claimed.id,
            lease_token=claimed.lease_token,
            lease_owner=claimed.lease_owner,
            expected_job_version=running.version,
            expected_task_version=claimed.version,
            result=_completed_result(),
        )

    assert rejected.value.code == "wrong_operation"


def test_result_correlation_must_match_job(temp_db_path) -> None:
    active = _active_preview(temp_db_path)

    with pytest.raises(import_jobs.BrowserResultPublicationRejected) as rejected:
        _publish(active, _completed_result(correlation_id="wrong-correlation"))

    assert rejected.value.code == "stale_lease"
    assert active.repository.get_job(active.job.id, OWNER).result_snapshot is None
