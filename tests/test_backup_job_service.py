from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.database.db import (
    claim_mobile_job,
    get_mobile_job,
    init_db,
    list_operational_events,
    request_cancel_mobile_job,
)
from app.database import db as database_module
from app.database import operations_repository
from app.mobile_api.services import job_service as job_service_module
from app.mobile_api.services.backup_job_service import BackupJobCoordinator, BackupSecretStore
from app.mobile_api.services.backup_service import BackupService
from app.mobile_api.services.job_service import JobTracker
from scripts.ops import BackupCancelled


async def wait_for_job(tracker: JobTracker, job_id: str) -> None:
    for _ in range(200):
        task = tracker._tasks.get(job_id)
        if task is None:
            return
        if task.done():
            await task
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


class RecordingTracker(JobTracker):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(db_path=db_path, heartbeat_interval_seconds=0.01)
        self.updates: list[dict[str, object]] = []

    def update_job(self, job_id: str, **changes: object) -> bool:
        self.updates.append(dict(changes))
        return super().update_job(job_id, **changes)


class FakeBackupService:
    def __init__(
        self,
        backup_dir: Path,
        *,
        steps: tuple[str, ...] = ("preparing", "collecting", "writing", "validating", "publishing"),
        hold: bool = False,
        failure: Exception | None = None,
        filename: str = "",
        encrypted: bool | None = None,
        secrets_included: bool | None = None,
    ) -> None:
        self.backup_dir = backup_dir.resolve()
        self.steps = steps
        self.hold = hold
        self.failure = failure
        self.filename = filename
        self.encrypted = encrypted
        self.secrets_included = secrets_included
        self.started = threading.Event()
        self.finished = threading.Event()
        self.release = threading.Event()
        self.cancel_observed = False
        self.call_count = 0
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = threading.Lock()

    def create_backup(
        self,
        *,
        include_audio: bool,
        include_exports: bool,
        include_job_logs: bool,
        include_secrets: bool,
        passphrase: str,
        cancel_check,
        progress_callback,
    ) -> dict:
        with self._lock:
            self.call_count += 1
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.started.set()
        try:
            for step in self.steps:
                progress_callback(step)
            if self.hold:
                deadline = time.monotonic() + 1
                while not self.release.wait(0.01) and time.monotonic() < deadline:
                    if cancel_check():
                        self.cancel_observed = True
                        raise BackupCancelled("Backup cancelled")
            if cancel_check():
                self.cancel_observed = True
                raise BackupCancelled("Backup cancelled")
            if self.failure is not None:
                raise self.failure
            return {
                "filename": self.filename
                or (
                    "novel-pipeline-backup-20260713-120000.tar.gz.enc"
                    if include_secrets
                    else "novel-pipeline-backup-20260713-120000.tar.gz"
                ),
                "encrypted": include_secrets if self.encrypted is None else self.encrypted,
                "secrets_included": (
                    include_secrets if self.secrets_included is None else self.secrets_included
                ),
            }
        finally:
            with self._lock:
                self.active_calls -= 1
            self.finished.set()


class DelayedCancellationBackupService(FakeBackupService):
    """Observes cancellation but stays active until the test releases it."""

    def create_backup(
        self,
        *,
        include_audio: bool,
        include_exports: bool,
        include_job_logs: bool,
        include_secrets: bool,
        passphrase: str,
        cancel_check,
        progress_callback,
    ) -> dict:
        with self._lock:
            self.call_count += 1
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.started.set()
        try:
            progress_callback("preparing")
            deadline = time.monotonic() + 2
            while not self.release.wait(0.01) and time.monotonic() < deadline:
                if cancel_check():
                    self.cancel_observed = True
            if self.cancel_observed or cancel_check():
                self.cancel_observed = True
                raise BackupCancelled("Backup cancelled")
            return {"filename": "novel-pipeline-backup-20260713-120000.tar.gz"}
        finally:
            with self._lock:
                self.active_calls -= 1
            self.finished.set()


class NoProgressCancellationBackupService:
    """Waits for release, then cooperatively checks cancellation before publication."""

    def __init__(self, backup_dir: Path) -> None:
        self.backup_dir = backup_dir.resolve()
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_observed = False
        self.publication_attempted = False
        self.call_count = 0

    def create_backup(
        self,
        *,
        include_audio: bool,
        include_exports: bool,
        include_job_logs: bool,
        include_secrets: bool,
        passphrase: str,
        cancel_check,
        progress_callback,
    ) -> dict:
        self.call_count += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("test did not release the backup provider")
        if cancel_check():
            self.cancel_observed = True
            raise BackupCancelled("Backup cancelled")
        self.publication_attempted = True
        return {
            "filename": "novel-pipeline-backup-20260713-120000.tar.gz",
            "encrypted": include_secrets,
            "secrets_included": include_secrets,
        }


class RecordingSecretStore(BackupSecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.discarded = threading.Event()

    def discard(self, job_id: str) -> None:
        super().discard(job_id)
        self.discarded.set()


def terminal_backup_events(db_path: Path, job_id: str) -> list[dict]:
    return [
        event
        for event in list_operational_events(db_path, limit=50, severities=())
        if event["event_type"] == "backup_job_terminal" and event["job_id"] == job_id
    ]


class OperationalEventWriteFailureConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        failures_remaining: list[int],
        attempts: list[str],
    ) -> None:
        self.connection = connection
        self.failures_remaining = failures_remaining
        self.attempts = attempts

    def __enter__(self):  # type: ignore[no-untyped-def]
        self.connection.__enter__()
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return self.connection.__exit__(*args)

    def execute(self, sql: str, parameters=()):  # type: ignore[no-untyped-def]
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("insert into operational_events"):
            event_type = str(parameters[0]) if parameters else ""
            if event_type == "backup_job_terminal":
                self.attempts.append(event_type)
                if self.failures_remaining[0] > 0:
                    self.failures_remaining[0] -= 1
                    raise sqlite3.OperationalError("injected backup terminal event write failure")
        return self.connection.execute(sql, parameters)

    def __getattr__(self, name: str):
        return getattr(self.connection, name)


def inject_operational_event_write_failures(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_count: int,
) -> list[str]:
    original_get_connection = database_module.get_connection
    attempts: list[str] = []
    failures_remaining = [failure_count]

    def failing_get_connection(db_path: Path):  # type: ignore[no-untyped-def]
        return OperationalEventWriteFailureConnection(
            original_get_connection(db_path),
            failures_remaining=failures_remaining,
            attempts=attempts,
        )

    monkeypatch.setattr(database_module, "get_connection", failing_get_connection)
    monkeypatch.setattr(operations_repository, "get_connection", failing_get_connection)
    return attempts


def test_backup_service_forwards_cancellation_and_progress_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = BackupService(backup_dir=backup_dir, data_dir=data_dir)
    cancel_check = lambda: False
    progress_callback = lambda step: None
    calls: list[tuple[str, object, object]] = []
    encrypted_path = backup_dir / "backup.tar.gz.enc"

    def create_encrypted_backup(**kwargs):
        calls.append((
            "create_encrypted",
            kwargs["cancel_check"],
            kwargs["progress_callback"],
            kwargs["record_event"],
        ))
        encrypted_path.write_bytes(b"encrypted")
        return encrypted_path

    monkeypatch.setattr(
        "app.mobile_api.services.backup_service.ops.create_encrypted_backup",
        create_encrypted_backup,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "list_backups",
        lambda: [{"filename": encrypted_path.name, "metadata_status": "READY"}],
    )

    item = service.create_backup(
        include_secrets=True,
        passphrase="correct horse",
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )

    assert item["filename"] == encrypted_path.name
    assert calls == [
        ("create_encrypted", cancel_check, progress_callback, False),
    ]


def test_backup_service_disables_the_legacy_ops_success_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = BackupService(backup_dir=backup_dir, data_dir=data_dir)
    backup_path = backup_dir / "backup.tar.gz"
    calls: list[bool] = []

    def create_backup(**kwargs):
        calls.append(kwargs["record_event"])
        backup_path.write_bytes(b"backup")
        return backup_path

    monkeypatch.setattr("app.mobile_api.services.backup_service.ops.create_backup", create_backup)
    monkeypatch.setattr(
        service,
        "list_backups",
        lambda: [{"filename": backup_path.name, "metadata_status": "READY"}],
    )

    service.create_backup()

    assert calls == [False]


def test_backup_service_secret_cancellation_never_uses_plain_publication_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = BackupService(backup_dir=backup_dir, data_dir=data_dir)
    monkeypatch.setattr(
        "app.mobile_api.services.backup_service.ops.create_encrypted_backup",
        lambda **kwargs: (_ for _ in ()).throw(BackupCancelled("Backup cancelled")),
    )
    monkeypatch.setattr(
        "app.mobile_api.services.backup_service.ops.create_backup",
        lambda **kwargs: pytest.fail("secret backup used plaintext creation path"),
    )

    with pytest.raises(BackupCancelled):
        service.create_backup(include_secrets=True, passphrase="correct horse")

    assert list(backup_dir.iterdir()) == []


def test_backup_secret_store_returns_a_secret_only_once() -> None:
    store = BackupSecretStore()

    store.put("job-1", "correct horse")

    assert store.take("job-1") == "correct horse"
    assert store.take("job-1") == ""


def test_backup_secret_store_expires_and_discards_secrets() -> None:
    now = 10.0
    store = BackupSecretStore(ttl_seconds=5, monotonic=lambda: now)
    store.put("expired", "old secret")
    store.put("discarded", "another secret")

    now = 16.0
    assert store.take("expired") == ""
    store.discard("discarded")
    assert store.take("discarded") == ""


def test_backup_secret_store_cannot_leak_through_repr_or_serialization() -> None:
    store = BackupSecretStore()
    store.put("job-1", "correct horse")

    assert "correct horse" not in repr(store)
    with pytest.raises((TypeError, AttributeError)):
        json.dumps(store, default=vars)


@pytest.mark.asyncio
async def test_backup_job_starts_after_returning_a_safe_persisted_job(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = RecordingTracker(temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="correct horse",
    )

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.job_type == "backup"
    assert job.total == 6
    assert job.params == {
        "include_audio": True,
        "include_exports": False,
        "include_job_logs": False,
        "include_secrets": True,
    }
    assert "correct horse" not in json.dumps(job.to_record())
    assert not service.started.is_set()

    await wait_for_job(tracker, job_id)
    persisted = JobTracker(db_path=temp_db_path).get_job(job_id)
    assert persisted is not None
    assert persisted.params["include_secrets"] is True
    assert "correct horse" not in json.dumps(persisted.to_record())


@pytest.mark.asyncio
async def test_backup_job_maps_progress_and_completes_with_safe_filename(tmp_path: Path) -> None:
    tracker = RecordingTracker()
    service = FakeBackupService(
        tmp_path / "backups",
        steps=("preparing", "collecting", "writing", "validating", "encrypting", "publishing"),
    )
    secrets = BackupSecretStore()
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=True,
        include_job_logs=True,
        include_secrets=True,
        passphrase="correct horse",
    )
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.state == "COMPLETED"
    assert job.progress == 6
    assert job.params["backup_filename"] == "novel-pipeline-backup-20260713-120000.tar.gz.enc"
    assert secrets.take(job_id) == ""
    states = [str(update.get("state")) for update in tracker.updates if update.get("state")]
    assert states == [
        "PREPARING_BACKUP",
        "PREPARING_BACKUP",
        "WRITING_BACKUP",
        "VALIDATING_BACKUP",
        "ENCRYPTING_BACKUP",
        "PUBLISHING_BACKUP",
    ]


@pytest.mark.asyncio
async def test_completed_backup_records_exactly_one_safe_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        steps=("preparing", "collecting", "writing", "validating", "encrypting", "publishing"),
        filename="private-staging\\finished-backup.tar.gz.enc",
    )
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="test credential",
    )
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.params["backup_filename"] == "finished-backup.tar.gz.enc"
    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    event = events[0]
    assert event["severity"] == "info"
    assert event["source"] == "backup_job_coordinator"
    assert event["message"] == "Backup job reached a terminal state"
    assert event["job_id"] == job_id
    duration_ms = event["details"].pop("duration_ms")
    assert isinstance(duration_ms, int)
    assert 0 <= duration_ms <= 2_147_483_647
    assert event["details"] == {
        "result": "completed",
        "backup_filename": "finished-backup.tar.gz.enc",
        "encrypted": True,
        "secrets_included": True,
    }


@pytest.mark.asyncio
async def test_completed_event_uses_authoritative_returned_backup_booleans(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        encrypted=True,
        secrets_included=False,
    )
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    await wait_for_job(tracker, job_id)

    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    assert events[0]["details"]["result"] == "completed"
    assert events[0]["details"]["encrypted"] is True
    assert events[0]["details"]["secrets_included"] is False


@pytest.mark.asyncio
async def test_failed_backup_records_one_sanitized_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups", failure=RuntimeError("raw failure marker"))
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=True,
        include_job_logs=True,
        include_secrets=False,
        passphrase="",
    )
    await wait_for_job(tracker, job_id)

    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    event = events[0]
    assert event["severity"] == "error"
    duration_ms = event["details"].pop("duration_ms")
    assert 0 <= duration_ms <= 2_147_483_647
    assert event["details"] == {
        "result": "failed",
        "encrypted": False,
        "secrets_included": False,
    }
    persisted_text = json.dumps(
        list_operational_events(temp_db_path, limit=50, severities=()),
        ensure_ascii=False,
    )
    assert "raw failure marker" not in persisted_text
    assert "raw failure marker" not in caplog.text


@pytest.mark.asyncio
async def test_expired_backup_secret_records_a_failed_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    ticks = iter((10.0, 11.0, 12.0))
    secrets = BackupSecretStore(ttl_seconds=0, monotonic=lambda: next(ticks))
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="test credential",
    )
    await wait_for_job(tracker, job_id)

    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    assert events[0]["severity"] == "error"
    assert events[0]["details"]["result"] == "failed"
    assert events[0]["details"]["encrypted"] is True
    assert events[0]["details"]["secrets_included"] is True
    assert "backup_filename" not in events[0]["details"]


@pytest.mark.asyncio
async def test_backup_jobs_for_one_directory_run_one_at_a_time(tmp_path: Path) -> None:
    tracker = JobTracker()
    service = FakeBackupService(tmp_path / "backups", hold=True)
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    first_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    second_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    for _ in range(100):
        if service.started.is_set():
            break
        await asyncio.sleep(0.01)

    assert service.call_count == 1
    service.release.set()
    await wait_for_job(tracker, first_id)
    await wait_for_job(tracker, second_id)

    assert service.call_count == 2
    assert service.max_active_calls == 1


@pytest.mark.asyncio
async def test_backup_cancel_is_cooperative_and_discards_secret(tmp_path: Path) -> None:
    tracker = JobTracker()
    service = FakeBackupService(tmp_path / "backups", hold=True)
    secrets = BackupSecretStore()
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="correct horse",
    )
    for _ in range(100):
        if service.started.is_set():
            break
        await asyncio.sleep(0.01)

    assert tracker.cancel_job(job_id)
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert service.cancel_observed
    assert job.cancel_requested is True
    assert job.status == "cancelled"
    assert secrets.take(job_id) == ""


@pytest.mark.asyncio
async def test_cooperative_backup_cancellation_records_one_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups", hold=True)
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    for _ in range(100):
        if service.started.is_set():
            break
        await asyncio.sleep(0.01)

    assert tracker.cancel_job(job_id)
    await wait_for_job(tracker, job_id)

    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    assert events[0]["severity"] == "warning"
    assert events[0]["details"]["result"] == "cancelled"
    assert events[0]["details"]["encrypted"] is False
    assert events[0]["details"]["secrets_included"] is False


def test_durable_cancelled_status_reconciles_owner_cache_without_flag(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="cancelled")
    assert job.cancel_requested is False

    assert coordinator._cancel_requested(job.job_id)
    assert job.cancel_requested is True


@pytest.mark.asyncio
async def test_remote_cancellation_before_owner_claim_is_terminalized_by_owner_without_archive_work(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    owner = JobTracker(db_path=temp_db_path)
    remote = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=owner, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = owner._tasks[job_id]

    cancel_accepted = remote.cancel_job(job_id)
    await owner_task

    cached = owner.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "cancel_accepted": cancel_accepted,
        "archive_call_count": service.call_count,
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["source"], event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "cancel_accepted": True,
        "archive_call_count": 0,
        "cached_state": ("cancelled", "CANCELED", True),
        "durable_state": ("cancelled", "CANCELED", True),
        "terminal_events": [("backup_job_coordinator", "warning", "cancelled")],
    }


@pytest.mark.asyncio
async def test_remote_durable_cancellation_reaches_running_provider_without_progress_callbacks(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    owner = JobTracker(db_path=temp_db_path)
    remote = JobTracker(db_path=temp_db_path)
    service = NoProgressCancellationBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=owner, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = owner._tasks[job_id]
    provider_started = await asyncio.to_thread(service.started.wait, 2)
    assert provider_started

    cancel_accepted = remote.cancel_job(job_id)
    cancellation_before_release = get_mobile_job(temp_db_path, job_id)
    service.release.set()
    await owner_task

    cached = owner.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert cancellation_before_release is not None
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "cancel_accepted": cancel_accepted,
        "durable_cancel_requested_before_release": cancellation_before_release[
            "cancel_requested"
        ],
        "provider_cancel_observed": service.cancel_observed,
        "publication_attempted": service.publication_attempted,
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["source"], event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "cancel_accepted": True,
        "durable_cancel_requested_before_release": True,
        "provider_cancel_observed": True,
        "publication_attempted": False,
        "cached_state": ("cancelled", "CANCELED", True),
        "durable_state": ("cancelled", "CANCELED", True),
        "terminal_events": [("backup_job_coordinator", "warning", "cancelled")],
    }


@pytest.mark.asyncio
async def test_durable_cancellation_winning_completion_write_records_cancelled_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    update_job = tracker.update_job

    def request_cancel_before_completion(job_id: str, **changes: object) -> bool:
        if changes.get("status") == "completed":
            assert request_cancel_mobile_job(temp_db_path, job_id=job_id)
        return update_job(job_id, **changes)

    monkeypatch.setattr(tracker, "update_job", request_cancel_before_completion)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = tracker._tasks[job_id]
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "cached_state": ("cancelled", "CANCELED", True),
        "durable_state": ("cancelled", "CANCELED", True),
        "terminal_events": [("warning", "cancelled")],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["provider", "expired_secret"])
async def test_durable_cancellation_winning_failure_write_records_cancelled_terminal_event(
    failure_mode: str,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        failure=RuntimeError("provider failed") if failure_mode == "provider" else None,
    )
    secret_store = None
    if failure_mode == "expired_secret":
        ticks = iter((10.0, 11.0, 12.0))
        secret_store = BackupSecretStore(ttl_seconds=0, monotonic=lambda: next(ticks))
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=service,
        secret_store=secret_store,
    )
    update_job = tracker.update_job

    def request_cancel_before_failure(job_id: str, **changes: object) -> bool:
        if changes.get("status") == "failed":
            assert request_cancel_mobile_job(temp_db_path, job_id=job_id)
        return update_job(job_id, **changes)

    monkeypatch.setattr(tracker, "update_job", request_cancel_before_failure)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=failure_mode == "expired_secret",
        passphrase="test credential" if failure_mode == "expired_secret" else "",
    )
    owner_task = tracker._tasks[job_id]
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "cached_state": ("cancelled", "CANCELED", True),
        "durable_state": ("cancelled", "CANCELED", True),
        "terminal_events": [("warning", "cancelled")],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_status", ["completed", "failed"])
async def test_reconciled_cancellation_survives_post_save_job_log_failure(
    requested_status: str,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        failure=RuntimeError("provider failed") if requested_status == "failed" else None,
    )
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    update_job = tracker.update_job
    cancellation_injected = False
    log_failures: list[str] = []

    def request_cancel_before_terminal_save(job_id: str, **changes: object) -> bool:
        nonlocal cancellation_injected
        if changes.get("status") == requested_status and not cancellation_injected:
            cancellation_injected = True
            assert request_cancel_mobile_job(temp_db_path, job_id=job_id)
        return update_job(job_id, **changes)

    record_job_log = job_service_module.record_job_log

    def fail_first_reconciled_transition(db_path: Path, **kwargs: object) -> int:
        details = kwargs.get("details")
        if (
            not log_failures
            and kwargs.get("event_type") == "state_transition"
            and isinstance(details, dict)
            and details.get("to_status") == "cancelled"
        ):
            log_failures.append(str(kwargs.get("job_id") or ""))
            raise RuntimeError("post-save job log failed")
        return record_job_log(db_path, **kwargs)

    monkeypatch.setattr(tracker, "update_job", request_cancel_before_terminal_save)
    monkeypatch.setattr(job_service_module, "record_job_log", fail_first_reconciled_transition)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = tracker._tasks[job_id]
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "cancellation_injected": cancellation_injected,
        "log_failures": log_failures,
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "cancellation_injected": True,
        "log_failures": [job_id],
        "cached_state": ("cancelled", "CANCELED", True),
        "durable_state": ("cancelled", "CANCELED", True),
        "terminal_events": [("warning", "cancelled")],
    }


def test_terminal_update_does_not_swallow_pre_persist_failure_for_cancelled_job(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="running")
    assert request_cancel_mobile_job(temp_db_path, job_id=job.job_id)
    assert tracker.update_job(job.job_id, status="completed")
    assert job.status == "cancelled"
    attempts: list[str] = []

    def fail_before_persist(*args: object, **kwargs: object) -> bool:
        attempts.append(str(args[0]))
        raise RuntimeError("pre-persist update failed")

    monkeypatch.setattr(tracker, "update_job", fail_before_persist)

    with pytest.raises(RuntimeError, match="pre-persist update failed"):
        coordinator._update_terminal_job(job.job_id, status="completed")
    assert attempts == [job.job_id, job.job_id]


def test_missing_job_terminal_update_raises_without_recording_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    job_id = "missing-backup-job"
    error: RuntimeError | None = None

    try:
        coordinator._update_terminal_job(
            job_id,
            status="cancelled",
            message="Backup cancelled",
            cancel_requested=True,
        )
    except RuntimeError as exc:
        error = exc

    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "error_type": type(error).__name__ if error is not None else None,
        "archive_call_count": service.call_count,
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "error_type": "RuntimeError",
        "archive_call_count": 0,
        "terminal_events": [],
    }


def test_stale_cached_deleted_backup_terminal_does_not_recreate_row_or_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="running")
    with database_module.get_connection(temp_db_path) as conn:
        conn.execute("DELETE FROM mobile_jobs WHERE job_id = ?", (job.job_id,))
        conn.commit()

    error: RuntimeError | None = None
    try:
        coordinator._update_terminal_job(
            job.job_id,
            status="cancelled",
            message="Backup cancelled",
            cancel_requested=True,
        )
    except RuntimeError as exc:
        error = exc

    assert {
        "error_type": type(error).__name__ if error is not None else None,
        "cached": job.job_id in tracker.jobs,
        "durable": get_mobile_job(temp_db_path, job.job_id),
        "terminal_events": terminal_backup_events(temp_db_path, job.job_id),
    } == {
        "error_type": "RuntimeError",
        "cached": False,
        "durable": None,
        "terminal_events": [],
    }


def test_backup_terminal_update_does_not_adopt_changed_ownership(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="running")
    with database_module.get_connection(temp_db_path) as conn:
        conn.execute(
            "UPDATE mobile_jobs SET owner_user_id = ? WHERE job_id = ?",
            ("different-owner", job.job_id),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="ownership changed"):
        coordinator._update_terminal_job(
            job.job_id,
            status="completed",
            progress=6,
            message="Backup completed: finished.tar.gz",
        )

    durable = get_mobile_job(temp_db_path, job.job_id)
    assert durable is not None
    assert job.job_id not in tracker.jobs
    assert (durable["owner_user_id"], durable["status"], durable["state"]) == (
        "different-owner",
        "running",
        "CLAIMED",
    )
    assert terminal_backup_events(temp_db_path, job.job_id) == []


def test_cross_tracker_cannot_terminalize_claimed_backup_owned_by_another_tracker(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    owner = JobTracker(db_path=temp_db_path)
    job = owner.create_job("backup")
    assert claim_mobile_job(
        temp_db_path,
        job_id=job.job_id,
        worker_id=owner.worker_id,
        lease_token="owner-lease-token",
    )
    remote = JobTracker(db_path=temp_db_path)
    loaded = remote.get_job(job.job_id)
    assert loaded is not None
    assert loaded.status == "running"
    coordinator = BackupJobCoordinator(
        tracker=remote,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )

    with pytest.raises(RuntimeError, match="ownership changed"):
        coordinator._update_terminal_job(
            job.job_id,
            status="completed",
            progress=6,
            message="Backup completed: foreign.tar.gz",
        )

    durable = get_mobile_job(temp_db_path, job.job_id)
    assert durable is not None
    assert job.job_id not in remote.jobs
    assert (durable["status"], durable["state"], durable["lease_owner"]) == (
        "running",
        "CLAIMED",
        owner.worker_id,
    )
    assert terminal_backup_events(temp_db_path, job.job_id) == []


def test_backup_terminal_event_failure_rolls_back_terminal_status(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="running")
    attempts = inject_operational_event_write_failures(monkeypatch, failure_count=10)

    with pytest.raises(sqlite3.OperationalError, match="injected backup terminal event write failure"):
        coordinator._update_terminal_job(
            job.job_id,
            status="completed",
            progress=6,
            message="Backup completed: finished.tar.gz",
            event_backup_filename="finished.tar.gz",
        )

    durable = get_mobile_job(temp_db_path, job.job_id)
    assert durable is not None
    assert attempts == ["backup_job_terminal", "backup_job_terminal"]
    assert (job.status, job.state) == ("running", "CLAIMED")
    assert (durable["status"], durable["state"]) == ("running", "CLAIMED")
    assert terminal_backup_events(temp_db_path, job.job_id) == []


@pytest.mark.asyncio
async def test_persistent_terminal_event_failure_cannot_generic_terminalize_backup(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    attempts = inject_operational_event_write_failures(monkeypatch, failure_count=10)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    await wait_for_job(tracker, job_id)

    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    assert attempts == ["backup_job_terminal", "backup_job_terminal"]
    assert durable["status"] not in {"completed", "failed", "cancelled", "canceled"}
    assert tracker.jobs[job_id].status == durable["status"]
    assert terminal_backup_events(temp_db_path, job_id) == []


def test_repeated_backup_terminal_persistence_records_exactly_one_event(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    coordinator = BackupJobCoordinator(
        tracker=tracker,
        backup_service=FakeBackupService(tmp_path / "backups"),
    )
    job = tracker.create_job("backup")
    assert tracker.update_job(job.job_id, status="running")
    attempts = inject_operational_event_write_failures(monkeypatch, failure_count=1)

    for attempt_number in range(2):
        coordinator._update_terminal_job(
            job.job_id,
            status="completed",
            progress=6,
            message="Backup completed: finished.tar.gz",
            event_backup_filename="finished.tar.gz",
        )
        if attempt_number == 0:
            first_attempt_events = terminal_backup_events(temp_db_path, job.job_id)
            assert [event["details"]["result"] for event in first_attempt_events] == [
                "completed"
            ]

    durable = get_mobile_job(temp_db_path, job.job_id)
    events = terminal_backup_events(temp_db_path, job.job_id)
    assert durable is not None
    assert (durable["status"], durable["state"]) == ("completed", "COMPLETED")
    assert attempts == [
        "backup_job_terminal",
        "backup_job_terminal",
        "backup_job_terminal",
    ]
    assert [(event["severity"], event["details"]["result"]) for event in events] == [
        ("info", "completed")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_status", "expected_severity"),
    [("completed", "info"), ("failed", "error")],
)
async def test_normal_terminal_result_survives_post_save_job_log_failure(
    requested_status: str,
    expected_severity: str,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        failure=RuntimeError("provider failed") if requested_status == "failed" else None,
    )
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    record_job_log = job_service_module.record_job_log
    log_failures: list[str] = []

    def fail_first_terminal_transition(db_path: Path, **kwargs: object) -> int:
        details = kwargs.get("details")
        if (
            not log_failures
            and kwargs.get("event_type") == "state_transition"
            and isinstance(details, dict)
            and details.get("to_status") == requested_status
        ):
            log_failures.append(str(kwargs.get("job_id") or ""))
            raise RuntimeError("post-save job log failed")
        return record_job_log(db_path, **kwargs)

    monkeypatch.setattr(job_service_module, "record_job_log", fail_first_terminal_transition)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = tracker._tasks[job_id]
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "log_failures": log_failures,
        "cached_status": cached.status,
        "durable_status": durable["status"],
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "log_failures": [job_id],
        "cached_status": requested_status,
        "durable_status": requested_status,
        "terminal_events": [(expected_severity, requested_status)],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_status", "expected_state", "expected_severity", "cancel_requested", "archive_calls"),
    [
        ("completed", "COMPLETED", "info", False, 1),
        ("failed", "FAILED", "error", False, 1),
        ("cancelled", "CANCELED", "warning", True, 0),
    ],
)
async def test_terminal_event_retries_one_shot_pre_persist_failure(
    requested_status: str,
    expected_state: str,
    expected_severity: str,
    cancel_requested: bool,
    archive_calls: int,
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(
        tmp_path / "backups",
        failure=RuntimeError("provider failed") if requested_status == "failed" else None,
    )
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    persist_terminal = job_service_module.commit_backup_job_terminal
    persist_failures: list[str] = []

    def fail_first_terminal_persist(db_path: Path, job: dict, **kwargs: object) -> dict:
        if str(job.get("status") or "") == requested_status and not persist_failures:
            persist_failures.append(str(job["job_id"]))
            raise RuntimeError("terminal state failed before persistence")
        return persist_terminal(db_path, job, **kwargs)

    monkeypatch.setattr(job_service_module, "commit_backup_job_terminal", fail_first_terminal_persist)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = tracker._tasks[job_id]
    if requested_status == "cancelled":
        assert tracker.cancel_job(job_id)
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert {
        "persist_failures": persist_failures,
        "archive_call_count": service.call_count,
        "cached_state": (cached.status, cached.state, cached.cancel_requested),
        "durable_state": (
            durable["status"],
            durable["state"],
            durable["cancel_requested"],
        ),
        "terminal_events": [
            (event["severity"], event["details"]["result"])
            for event in events
        ],
    } == {
        "persist_failures": [job_id],
        "archive_call_count": archive_calls,
        "cached_state": (requested_status, expected_state, cancel_requested),
        "durable_state": (requested_status, expected_state, cancel_requested),
        "terminal_events": [(expected_severity, requested_status)],
    }


@pytest.mark.asyncio
async def test_cancelled_terminal_event_survives_post_save_job_log_failure(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    record_job_log = job_service_module.record_job_log
    log_failures: list[str] = []

    def fail_cancelled_transition_log(db_path: Path, **kwargs: object) -> int:
        details = kwargs.get("details")
        if (
            not log_failures
            and kwargs.get("event_type") == "state_transition"
            and isinstance(details, dict)
            and details.get("to_status") == "cancelled"
        ):
            log_failures.append(str(kwargs.get("job_id") or ""))
            raise RuntimeError("post-save cancelled log failed")
        return record_job_log(db_path, **kwargs)

    monkeypatch.setattr(job_service_module, "record_job_log", fail_cancelled_transition_log)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    owner_task = tracker._tasks[job_id]
    assert tracker.cancel_job(job_id)
    await owner_task

    cached = tracker.jobs[job_id]
    durable = get_mobile_job(temp_db_path, job_id)
    assert durable is not None
    events = terminal_backup_events(temp_db_path, job_id)
    assert log_failures == [job_id]
    assert (cached.status, cached.state, cached.cancel_requested) == (
        "cancelled",
        "CANCELED",
        True,
    )
    assert (durable["status"], durable["state"], durable["cancel_requested"]) == (
        "cancelled",
        "CANCELED",
        True,
    )
    assert [
        (event["severity"], event["details"]["result"])
        for event in events
    ] == [("warning", "cancelled")]


@pytest.mark.asyncio
async def test_cancellation_before_archive_work_records_one_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )

    assert tracker.cancel_job(job_id)
    pending = tracker.get_job(job_id)
    assert pending is not None
    assert pending.status == "queued"
    assert pending.cancel_requested is True
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.status == "cancelled"
    assert not service.started.is_set()
    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    assert events[0]["severity"] == "warning"
    assert events[0]["details"]["result"] == "cancelled"


@pytest.mark.asyncio
async def test_external_cancellation_while_waiting_for_lock_records_terminal_event_without_work(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path, heartbeat_interval_seconds=0.01)
    service = DelayedCancellationBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)
    first_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    for _ in range(100):
        if service.started.is_set():
            break
        await asyncio.sleep(0.01)

    second_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    for _ in range(100):
        second = tracker.get_job(second_id)
        if second is not None and second.status == "running":
            break
        await asyncio.sleep(0.01)

    assert service.call_count == 1
    tracker._tasks[second_id].cancel()
    await wait_for_job(tracker, second_id)

    persisted = JobTracker(db_path=temp_db_path).get_job(second_id)
    assert persisted is not None
    assert persisted.status == "cancelled"
    assert service.call_count == 1
    events = terminal_backup_events(temp_db_path, second_id)
    assert len(events) == 1
    assert events[0]["details"]["result"] == "cancelled"

    service.release.set()
    await wait_for_job(tracker, first_id)


@pytest.mark.asyncio
async def test_terminal_audit_failure_is_retried_with_atomic_job_outcome(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups")
    attempts = inject_operational_event_write_failures(monkeypatch, failure_count=1)
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    await wait_for_job(tracker, job_id)

    persisted = JobTracker(db_path=temp_db_path).get_job(job_id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert attempts == ["backup_job_terminal", "backup_job_terminal"]
    events = terminal_backup_events(temp_db_path, job_id)
    assert [(event["severity"], event["details"]["result"]) for event in events] == [
        ("info", "completed")
    ]


@pytest.mark.asyncio
async def test_generic_failure_audit_error_does_not_block_the_dedicated_terminal_event(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    init_db(temp_db_path)
    tracker = JobTracker(db_path=temp_db_path)
    service = FakeBackupService(tmp_path / "backups", failure=RuntimeError("worker failure marker"))
    original_record_event = job_service_module.record_operational_event
    generic_attempts: list[str] = []

    def fail_generic_failure_audit(db_path: Path, **kwargs) -> int:
        if kwargs.get("event_type") == "job_failure":
            generic_attempts.append(str(kwargs.get("job_id") or ""))
            raise RuntimeError("raw tracker audit marker")
        return original_record_event(db_path, **kwargs)

    monkeypatch.setattr(job_service_module, "record_operational_event", fail_generic_failure_audit)
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    await wait_for_job(tracker, job_id)

    persisted = JobTracker(db_path=temp_db_path).get_job(job_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert generic_attempts == [job_id]
    events = terminal_backup_events(temp_db_path, job_id)
    assert len(events) == 1
    assert events[0]["details"]["result"] == "failed"
    assert "raw tracker audit marker" not in caplog.text


@pytest.mark.asyncio
async def test_external_wrapper_cancel_holds_directory_lock_until_worker_exits(
    tmp_path: Path,
) -> None:
    tracker = JobTracker()
    service = DelayedCancellationBackupService(tmp_path / "backups")
    secrets = RecordingSecretStore()
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)
    first_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="correct horse",
    )
    for _ in range(100):
        if service.started.is_set():
            break
        await asyncio.sleep(0.01)

    first_wrapper = tracker._tasks[first_id]
    first_wrapper.cancel()
    second_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=False,
        passphrase="",
    )
    for _ in range(100):
        if service.cancel_observed:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)

    first_job = tracker.get_job(first_id)
    assert first_job is not None
    assert service.cancel_observed
    assert service.call_count == 1
    assert service.max_active_calls == 1
    assert first_job.status not in {"cancelled", "canceled", "completed", "failed", "interrupted"}
    assert not secrets.discarded.is_set()

    service.release.set()
    await wait_for_job(tracker, first_id)
    await wait_for_job(tracker, second_id)

    first_job = tracker.get_job(first_id)
    assert first_job is not None
    assert first_job.status == "cancelled"
    assert service.call_count == 2
    assert service.max_active_calls == 1
    assert secrets.discarded.is_set()
    assert secrets.take(first_id) == ""


@pytest.mark.asyncio
async def test_expired_encryption_secret_fails_without_starting_or_leaking(tmp_path: Path) -> None:
    ticks = iter((10.0, 11.0, 12.0))
    secrets = BackupSecretStore(ttl_seconds=0, monotonic=lambda: next(ticks))
    tracker = JobTracker()
    service = FakeBackupService(tmp_path / "backups")
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="correct horse",
    )
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert not service.started.is_set()
    assert "correct horse" not in json.dumps(job.to_record())
    assert secrets.take(job_id) == ""


@pytest.mark.asyncio
async def test_backup_failure_is_sanitized_and_discards_secret(tmp_path: Path) -> None:
    tracker = JobTracker()
    service = FakeBackupService(tmp_path / "backups", failure=RuntimeError("correct horse"))
    secrets = BackupSecretStore()
    coordinator = BackupJobCoordinator(tracker=tracker, backup_service=service, secret_store=secrets)

    job_id = coordinator.start_backup_job(
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
        include_secrets=True,
        passphrase="correct horse",
    )
    await wait_for_job(tracker, job_id)

    job = tracker.get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert "correct horse" not in json.dumps(job.to_record())
    assert secrets.take(job_id) == ""
