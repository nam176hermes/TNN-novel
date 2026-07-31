from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any

import pytest

from app.recovery_receipts import (
    EXTERNAL_BACKUP_RECEIPT,
    MAX_RECEIPT_BYTES,
    RESTORE_DRILL_RECEIPT,
    publish_recovery_receipt,
    read_recovery_receipt,
)


HASH_ID = "sha256:" + "a" * 64
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
EXTERNAL_COUNTS = {
    "archive_verified": 1,
    "metadata_verified": 1,
    "checksum_verified": 1,
    "remote_uploads_verified": 3,
    "remote_metadata_verified": 2,
}
RESTORE_COUNTS = {
    "checksum_verified": 1,
    "sqlite_integrity_checks": 1,
    "foreign_key_violations": 0,
    "artifact_paths_scanned": 0,
    "api_readiness_checks": 1,
    "authenticated_reader_smokes": 1,
}


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "passed",
        "completed_at": NOW.isoformat(),
        "archive_hash_id": HASH_ID,
        "validation_counts": EXTERNAL_COUNTS,
        "producer_version": "release-a",
    }
    payload.update(overrides)
    return payload


def _write(data_dir: Path, payload: object) -> Path:
    path = data_dir / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_receipt_is_bounded() -> None:
    result = read_recovery_receipt(Path("/does-not-exist"), "external_backup", expected_release="release-a", now=NOW)
    assert result == {
        "state": "missing",
        "age_seconds": None,
        "completed_at": None,
        "archive_hash_id": None,
        "validation_counts": {},
        "producer_version": None,
        "threshold_seconds": 172800,
    }


@pytest.mark.parametrize(
    "content",
    ["{", json.dumps({"status": "passed"}), json.dumps(_payload(extra="private")), json.dumps(_payload(status="failed")), json.dumps(_payload(completed_at="2026-07-24T12:00:00")), json.dumps(_payload(archive_hash_id="sha256:" + "A" * 64)), json.dumps(_payload(validation_counts={"secret_count": 1})), json.dumps(_payload(validation_counts={"checksum_verified": -1})), json.dumps(_payload(producer_version="bad/version"))],
)
def test_corrupt_json_or_schema_never_leaks(content: str, tmp_path: Path) -> None:
    path = tmp_path / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    result = read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)
    assert result["state"] == "corrupt"
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert "private" not in serialized
    assert "secret_count" not in serialized


def test_deeply_nested_json_is_bounded_corrupt_instead_of_recursion_error(tmp_path: Path) -> None:
    path = tmp_path / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True)
    path.write_text("[" * 1200 + "0" + "]" * 1200, encoding="utf-8")

    result = read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)

    assert result["state"] == "corrupt"


def test_symlink_and_oversize_are_corrupt(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_payload()), encoding="utf-8")
    path = tmp_path / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "corrupt"
    path.unlink()
    path.write_bytes(b"x" * (MAX_RECEIPT_BYTES + 1))
    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "corrupt"


def test_fifo_receipt_is_rejected_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True)
    os.mkfifo(path)

    captured: list[dict[str, Any]] = []
    worker = threading.Thread(
        target=lambda: captured.append(
            read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=1)

    assert not worker.is_alive(), "receipt reader blocked on FIFO"
    assert captured[0]["state"] == "corrupt"


def test_symlinked_parent_is_corrupt_and_publisher_refuses_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "logs").symlink_to(outside, target_is_directory=True)

    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "corrupt"
    with pytest.raises(OSError):
        publish_recovery_receipt(
            tmp_path / EXTERNAL_BACKUP_RECEIPT,
            archive_hash_id=HASH_ID,
            validation_counts=EXTERNAL_COUNTS,
            producer_version="release-a",
            completed_at=NOW,
        )
    assert not (outside / "runtime" / "external-backup.receipt.json").exists()


@pytest.mark.parametrize(
    "content",
    [
        '{"status":"failed","status":"passed","completed_at":"2026-07-24T12:00:00+00:00","archive_hash_id":"sha256:' + "a" * 64 + '","validation_counts":{"checksum_verified":1},"producer_version":"release-a"}',
        json.dumps(_payload(completed_at="2026-07-24 12:00:00+00:00")),
        json.dumps(_payload(completed_at="2026-07-24T12:00:00Z")),
        json.dumps(_payload(completed_at="2026-07-24T12:00:00.1234567+00:00")),
        json.dumps(_payload(completed_at="2026-07-24T12:00:00.000000+00:00")),
        json.dumps(_payload(completed_at="2026-07-24T12:00:00.1+00:00")),
    ],
)
def test_duplicate_keys_and_noncanonical_timestamps_are_corrupt(content: str, tmp_path: Path) -> None:
    path = tmp_path / EXTERNAL_BACKUP_RECEIPT
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "corrupt"


@pytest.mark.parametrize(
    "counts",
    [
        {"checksum_verified": 1},
        {**EXTERNAL_COUNTS, "checksum_verified": 0},
        RESTORE_COUNTS,
    ],
)
def test_external_backup_requires_its_exact_successful_validation_contract(
    counts: dict[str, int], tmp_path: Path
) -> None:
    _write(tmp_path, _payload(validation_counts=counts))

    result = read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)

    assert result["state"] == "corrupt"


def test_restore_drill_requires_its_exact_successful_validation_contract(tmp_path: Path) -> None:
    path = tmp_path / RESTORE_DRILL_RECEIPT
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_payload(validation_counts={"checksum_verified": 1})), encoding="utf-8")
    assert read_recovery_receipt(tmp_path, "restore_drill", expected_release="release-a", now=NOW)["state"] == "corrupt"

    path.write_text(json.dumps(_payload(validation_counts=RESTORE_COUNTS)), encoding="utf-8")
    assert read_recovery_receipt(tmp_path, "restore_drill", expected_release="release-a", now=NOW)["state"] == "fresh"


def test_fixed_receipt_publisher_rejects_semantically_incomplete_counts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="receipt kind"):
        publish_recovery_receipt(
            tmp_path / EXTERNAL_BACKUP_RECEIPT,
            archive_hash_id=HASH_ID,
            validation_counts={"checksum_verified": 1},
            producer_version="release-a",
            completed_at=NOW,
        )


def test_future_wrong_release_stale_and_fresh(tmp_path: Path) -> None:
    path = _write(tmp_path, _payload(completed_at=(NOW + timedelta(seconds=301)).isoformat()))
    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "future"
    path.write_text(json.dumps(_payload(producer_version="release-b")), encoding="utf-8")
    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "wrong_release"
    path.write_text(json.dumps(_payload(completed_at=(NOW - timedelta(seconds=172801)).isoformat())), encoding="utf-8")
    assert read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)["state"] == "stale"
    path.write_text(json.dumps(_payload(completed_at=(NOW - timedelta(seconds=12)).isoformat())), encoding="utf-8")
    result = read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)
    assert result["state"] == "fresh"
    assert result["age_seconds"] == 12
    assert result["archive_hash_id"] == HASH_ID


def test_threshold_overrides_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, _payload(completed_at=(NOW - timedelta(seconds=11)).isoformat()))
    monkeypatch.setenv("NOVEL_EXTERNAL_BACKUP_MAX_AGE_SECONDS", "10")
    monkeypatch.setenv("NOVEL_RECOVERY_RECEIPT_FUTURE_SKEW_SECONDS", "1")
    result = read_recovery_receipt(tmp_path, "external_backup", expected_release="release-a", now=NOW)
    assert result["state"] == "stale"
    assert result["threshold_seconds"] == 10


def test_publisher_permissions_atomic_replace_and_exact_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / EXTERNAL_BACKUP_RECEIPT
    replaced: list[tuple[object, object]] = []
    original_replace = os.replace

    def tracked_replace(source: Any, destination: Any, **kwargs: Any) -> None:
        replaced.append((source, destination))
        original_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", tracked_replace)
    publish_recovery_receipt(output, archive_hash_id=HASH_ID, validation_counts=EXTERNAL_COUNTS, producer_version="release-a", completed_at=NOW)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload) == {"status", "completed_at", "archive_hash_id", "validation_counts", "producer_version"}
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert replaced and replaced[0][1] == output.name
    assert not list(output.parent.glob(f".{output.name}.*"))


@pytest.mark.parametrize("removed_key", ["books", "chapters"])
def test_unused_table_counts_are_rejected(removed_key: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="validation count key"):
        publish_recovery_receipt(
            tmp_path / EXTERNAL_BACKUP_RECEIPT,
            archive_hash_id=HASH_ID,
            validation_counts={removed_key: 1},
            producer_version="release-a",
            completed_at=NOW,
        )


def test_publisher_rejects_empty_validation_counts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="validation counts"):
        publish_recovery_receipt(
            tmp_path / EXTERNAL_BACKUP_RECEIPT,
            archive_hash_id=HASH_ID,
            validation_counts={},
            producer_version="release-a",
            completed_at=NOW,
        )
