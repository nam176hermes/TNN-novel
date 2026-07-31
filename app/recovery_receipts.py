"""Strict, non-sensitive recovery receipt parsing and atomic publication."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Literal


ReceiptKind = Literal["external_backup", "restore_drill"]
ReceiptState = Literal["missing", "corrupt", "future", "wrong_release", "stale", "fresh"]


EXTERNAL_BACKUP_RECEIPT = Path("logs/runtime/external-backup.receipt.json")
RESTORE_DRILL_RECEIPT = Path("logs/runtime/restore-drill.receipt.json")
MAX_RECEIPT_BYTES = 16 * 1024
MAX_VALIDATION_COUNT = 1_000_000_000
MAX_VALIDATION_KEYS = 16

_RECEIPT_KEYS = {
    "status",
    "completed_at",
    "archive_hash_id",
    "validation_counts",
    "producer_version",
}
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
_RELEASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_COUNT_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_UTC_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00:00"
)
_ALLOWED_COUNTS = {
    "archive_verified",
    "metadata_verified",
    "checksum_verified",
    "remote_uploads_verified",
    "remote_metadata_verified",
    "sqlite_integrity_checks",
    "foreign_key_violations",
    "artifact_paths_scanned",
    "api_readiness_checks",
    "authenticated_reader_smokes",
}
_COUNT_RULES: dict[ReceiptKind, dict[str, tuple[int, int]]] = {
    "external_backup": {
        "archive_verified": (1, 1),
        "metadata_verified": (1, 1),
        "checksum_verified": (1, 1),
        "remote_uploads_verified": (3, 3),
        "remote_metadata_verified": (2, 2),
    },
    "restore_drill": {
        "checksum_verified": (1, 1),
        "sqlite_integrity_checks": (1, 1),
        "foreign_key_violations": (0, 0),
        "artifact_paths_scanned": (0, MAX_VALIDATION_COUNT),
        "api_readiness_checks": (1, 1),
        "authenticated_reader_smokes": (1, 1),
    },
}
_KIND_CONFIG = {
    "external_backup": (EXTERNAL_BACKUP_RECEIPT, "NOVEL_EXTERNAL_BACKUP_MAX_AGE_SECONDS", 172800),
    "restore_drill": (RESTORE_DRILL_RECEIPT, "NOVEL_RESTORE_DRILL_MAX_AGE_SECONDS", 691200),
}

def _bounded_positive_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if 1 <= value <= 315_360_000 else default


def _bounded_non_negative_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if 0 <= value <= 315_360_000 else default


def _empty(state: ReceiptState, threshold: int) -> dict[str, Any]:
    return {
        "state": state,
        "age_seconds": None,
        "completed_at": None,
        "archive_hash_id": None,
        "validation_counts": {},
        "producer_version": None,
        "threshold_seconds": threshold,
    }


def _validate_counts(value: object, kind: ReceiptKind | None = None) -> dict[str, int]:
    if not isinstance(value, dict) or not value or len(value) > MAX_VALIDATION_KEYS:
        raise ValueError("invalid validation counts")
    result: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or not _COUNT_KEY_RE.fullmatch(key) or key not in _ALLOWED_COUNTS:
            raise ValueError("invalid validation count key")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_VALIDATION_COUNT:
            raise ValueError("invalid validation count")
        result[key] = count
    if kind is not None:
        rules = _COUNT_RULES[kind]
        if set(result) != set(rules):
            raise ValueError("invalid validation counts for receipt kind")
        for key, (minimum, maximum) in rules.items():
            if not minimum <= result[key] <= maximum:
                raise ValueError("unsuccessful validation count")
    return result


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp is not UTC")
    canonical = parsed.astimezone(timezone.utc)
    if value != canonical.isoformat():
        raise ValueError("timestamp is not canonical UTC")
    return canonical


def _strict_json_object(raw: bytes) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate receipt key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)


def _open_directory_path(path: Path, *, create: bool) -> int:
    """Open an absolute directory path without following any symlink component."""

    path = Path(path)
    if not path.is_absolute():
        raise ValueError("directory path must be absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_receipt_directory(data_dir: Path) -> int:
    descriptor = _open_directory_path(Path(data_dir), create=False)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        for component in ("logs", "runtime"):
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_payload(payload: object, kind: ReceiptKind | None = None) -> tuple[datetime, str, dict[str, int], str]:
    if not isinstance(payload, dict) or set(payload) != _RECEIPT_KEYS:
        raise ValueError("invalid receipt keys")
    if payload["status"] != "passed":
        raise ValueError("invalid receipt status")
    completed = _parse_timestamp(payload["completed_at"])
    hash_id = payload["archive_hash_id"]
    producer = payload["producer_version"]
    if not isinstance(hash_id, str) or not _HASH_RE.fullmatch(hash_id):
        raise ValueError("invalid hash identifier")
    if not isinstance(producer, str) or not _RELEASE_RE.fullmatch(producer):
        raise ValueError("invalid producer version")
    return completed, hash_id, _validate_counts(payload["validation_counts"], kind), producer


def read_recovery_receipt(
    data_dir: Path,
    kind: ReceiptKind,
    *,
    expected_release: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read one fixed receipt and return only a bounded, safe snapshot."""

    relative_path, threshold_env, default_threshold = _KIND_CONFIG[kind]
    threshold = _bounded_positive_env(threshold_env, default_threshold)
    try:
        directory_fd = _open_receipt_directory(Path(data_dir))
    except FileNotFoundError:
        return _empty("missing", threshold)
    except OSError:
        return _empty("corrupt", threshold)
    try:
        descriptor = os.open(
            relative_path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        os.close(directory_fd)
        return _empty("missing", threshold)
    except OSError:
        os.close(directory_fd)
        return _empty("corrupt", threshold)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECEIPT_BYTES:
            raise ValueError("receipt is not a bounded regular file")
        raw = os.read(descriptor, MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise ValueError("receipt too large")
        completed, hash_id, counts, producer = _validate_payload(_strict_json_object(raw), kind)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, json.JSONDecodeError):
        return _empty("corrupt", threshold)
    finally:
        os.close(descriptor)
        os.close(directory_fd)

    resolved_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    delta = (resolved_now - completed).total_seconds()
    future_skew = _bounded_non_negative_env("NOVEL_RECOVERY_RECEIPT_FUTURE_SKEW_SECONDS", 300)
    if delta < -future_skew:
        state: ReceiptState = "future"
        age: int | None = None
    else:
        age = max(0, int(delta))
        if producer != expected_release:
            state = "wrong_release"
        elif age > threshold:
            state = "stale"
        else:
            state = "fresh"
    return {
        "state": state,
        "age_seconds": age,
        "completed_at": completed.isoformat(),
        "archive_hash_id": hash_id,
        "validation_counts": counts,
        "producer_version": producer,
        "threshold_seconds": threshold,
    }


def publish_recovery_receipt(
    output: Path,
    *,
    archive_hash_id: str,
    validation_counts: dict[str, int],
    producer_version: str,
    completed_at: datetime | None = None,
) -> None:
    """Validate and atomically publish a mode-0600 receipt."""

    output = Path(output)
    if not output.is_absolute() or output.name in {"", ".", ".."}:
        raise ValueError("receipt output must be an absolute file path")
    timestamp = (completed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "status": "passed",
        "completed_at": timestamp.isoformat(),
        "archive_hash_id": archive_hash_id,
        "validation_counts": validation_counts,
        "producer_version": producer_version,
    }
    output_kind: ReceiptKind | None = None
    if output.name == EXTERNAL_BACKUP_RECEIPT.name:
        output_kind = "external_backup"
    elif output.name == RESTORE_DRILL_RECEIPT.name:
        output_kind = "restore_drill"
    _validate_payload(payload, output_kind)
    payload_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    parent_fd = _open_directory_path(output.parent, create=True)
    os.fchmod(parent_fd, 0o700)
    temporary_name = f".{output.name}.{secrets.token_hex(12)}"
    fd = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=parent_fd,
    )
    try:
        offset = 0
        while offset < len(payload_bytes):
            offset += os.write(fd, payload_bytes[offset:])
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(
            temporary_name,
            output.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(parent_fd)
