from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from app.database.db import init_db
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
    ) -> None:
        self.backup_dir = backup_dir.resolve()
        self.steps = steps
        self.hold = hold
        self.failure = failure
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
                "filename": "novel-pipeline-backup-20260713-120000.tar.gz.enc"
                if include_secrets
                else "novel-pipeline-backup-20260713-120000.tar.gz"
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


class RecordingSecretStore(BackupSecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.discarded = threading.Event()

    def discard(self, job_id: str) -> None:
        super().discard(job_id)
        self.discarded.set()


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
    plain_path = backup_dir / "backup.tar.gz"
    encrypted_path = backup_dir / "backup.tar.gz.enc"

    def create_backup(**kwargs):
        calls.append(("create", kwargs["cancel_check"], kwargs["progress_callback"]))
        plain_path.write_bytes(b"plain")
        return plain_path

    def encrypt_backup_archive(path: Path, **kwargs):
        assert path == plain_path
        calls.append(("encrypt", kwargs["cancel_check"], kwargs["progress_callback"]))
        encrypted_path.write_bytes(b"encrypted")
        return encrypted_path

    monkeypatch.setattr("app.mobile_api.services.backup_service.ops.create_backup", create_backup)
    monkeypatch.setattr("app.mobile_api.services.backup_service.ops.encrypt_backup_archive", encrypt_backup_archive)
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
        ("create", cancel_check, progress_callback),
        ("encrypt", cancel_check, progress_callback),
    ]


def test_backup_service_removes_plain_secret_archive_when_encryption_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    service = BackupService(backup_dir=backup_dir, data_dir=data_dir)
    plain_path = backup_dir / "backup.tar.gz"

    def create_backup(**kwargs):
        plain_path.write_bytes(b"plain secrets")
        plain_path.with_suffix(plain_path.suffix + ".manifest.json").write_text("{}", encoding="utf-8")
        return plain_path

    monkeypatch.setattr("app.mobile_api.services.backup_service.ops.create_backup", create_backup)
    monkeypatch.setattr(
        "app.mobile_api.services.backup_service.ops.encrypt_backup_archive",
        lambda *args, **kwargs: (_ for _ in ()).throw(BackupCancelled("Backup cancelled")),
    )

    with pytest.raises(BackupCancelled):
        service.create_backup(include_secrets=True, passphrase="correct horse")

    assert not plain_path.exists()
    assert not plain_path.with_suffix(plain_path.suffix + ".manifest.json").exists()


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
