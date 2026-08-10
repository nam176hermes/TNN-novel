"""Redacted operational alert delivery and durable local receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlsplit

import requests


SCHEMA_VERSION = 1
MAX_TIMEOUT_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RECEIPT_BYTES = 8 * 1024

_ALERT_CODE_PRIORITY = {
    "backup_failure": ("backup_failed",),
    "wrong_release_receipt": (
        "external_backup_wrong_release",
        "restore_drill_wrong_release",
    ),
    "worker_stale": ("worker_stale",),
    "stuck_jobs": ("queue_stale",),
}
SUPPORTED_ALERT_CLASSES = {
    alert_class: frozenset(codes)
    for alert_class, codes in _ALERT_CODE_PRIORITY.items()
}
_RECEIPT_FILENAMES = {
    "backup_failure": "alert-backup_failure.receipt.json",
    "wrong_release_receipt": "alert-wrong_release_receipt.receipt.json",
    "worker_stale": "alert-worker_stale.receipt.json",
    "stuck_jobs": "alert-stuck_jobs.receipt.json",
}
_DEFAULT_SEVERITY = {
    "backup_failed": "warning",
    "external_backup_wrong_release": "warning",
    "restore_drill_wrong_release": "warning",
    "worker_stale": "critical",
    "queue_stale": "warning",
}
_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "alert_class",
    "code",
    "attempt_count",
    "observed_at",
    "delivered_at",
    "release_id",
    "fingerprint",
    "http_status",
}
_SAFE_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,127}")
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
_PROCESS_LOCK = threading.RLock()


DeliveryStatus = Literal["delivered", "failed", "resolved"]


class _ResponseLike(Protocol):
    status_code: int


class _SessionLike(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> _ResponseLike: ...


@dataclass(frozen=True)
class AlertIncident:
    alert_class: str
    code: str
    severity: str
    release_id: str
    observed_at: str
    fingerprint: str


@dataclass(frozen=True)
class AlertDeliveryConfig:
    webhook_url: str
    bearer_token: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = 3
    allow_loopback_http: bool = False

    def __post_init__(self) -> None:
        webhook_url = str(self.webhook_url or "").strip()
        _validate_webhook_url(webhook_url, allow_loopback_http=bool(self.allow_loopback_http))
        bearer_token = str(self.bearer_token or "")
        if len(bearer_token) > 4096 or any(character in bearer_token for character in "\r\n\0"):
            raise ValueError("Webhook bearer token is invalid")
        try:
            max_attempts = int(self.max_attempts)
        except (OverflowError, TypeError, ValueError):
            max_attempts = 3
        max_attempts = min(3, max(1, max_attempts))
        try:
            timeout_seconds = float(self.timeout_seconds)
        except (OverflowError, TypeError, ValueError):
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = min(MAX_TIMEOUT_SECONDS, max(0.05, timeout_seconds))
        object.__setattr__(self, "webhook_url", webhook_url)
        object.__setattr__(self, "bearer_token", bearer_token)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "max_attempts", max_attempts)
        object.__setattr__(self, "allow_loopback_http", bool(self.allow_loopback_http))


@dataclass(frozen=True)
class DeliveryReceipt:
    status: DeliveryStatus
    alert_class: str
    code: str
    attempt_count: int
    observed_at: str
    delivered_at: str | None
    release_id: str
    fingerprint: str
    http_status: int | None


def _validate_webhook_url(url: str, *, allow_loopback_http: bool) -> None:
    if not url or len(url) > 4096 or any(ord(character) < 32 for character in url):
        raise ValueError("Webhook URL must use HTTPS")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError("Webhook URL must use HTTPS") from None
    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Webhook URL must use HTTPS")
    if parsed.scheme.lower() == "https":
        return
    if parsed.scheme.lower() != "http" or not allow_loopback_http:
        raise ValueError("Webhook URL must use HTTPS")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        raise ValueError("Synthetic HTTP webhook must use a literal loopback address") from None
    if not address.is_loopback:
        raise ValueError("Synthetic HTTP webhook must use a literal loopback address")


def _canonical_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("Operational alert timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Operational alert timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("Operational alert timestamp is invalid")
    return parsed.astimezone(timezone.utc).isoformat()


def _safe_release_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_RELEASE_ID.fullmatch(value):
        raise ValueError("Operational alert release ID is invalid")
    return value


def _snapshot_metadata(snapshot: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(snapshot, dict):
        raise ValueError("Operational snapshot is invalid")
    release = snapshot.get("release")
    if not isinstance(release, dict):
        raise ValueError("Operational snapshot is invalid")
    return _safe_release_id(release.get("release_id")), _canonical_timestamp(
        snapshot.get("generated_at")
    )


def _incident_fingerprint(alert_class: str, code: str, release_id: str) -> str:
    canonical = json.dumps(
        {
            "alert_class": alert_class,
            "code": code,
            "release_id": release_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def incidents_from_snapshot(snapshot: dict[str, Any]) -> tuple[AlertIncident, ...]:
    """Select at most one deterministic active incident for each supported class."""

    release_id, observed_at = _snapshot_metadata(snapshot)
    raw_alerts = snapshot.get("alerts")
    if not isinstance(raw_alerts, (list, tuple)):
        raise ValueError("Operational snapshot alerts are invalid")

    severities: dict[str, str] = {}
    supported_codes = frozenset().union(*SUPPORTED_ALERT_CLASSES.values())
    for raw_alert in raw_alerts:
        if not isinstance(raw_alert, dict):
            continue
        code = raw_alert.get("code")
        if not isinstance(code, str) or code not in supported_codes:
            continue
        severity = raw_alert.get("severity")
        normalized = severity if severity in {"warning", "critical"} else _DEFAULT_SEVERITY[code]
        previous = severities.get(code)
        severities[code] = "critical" if "critical" in {previous, normalized} else "warning"

    incidents: list[AlertIncident] = []
    for alert_class, priority in _ALERT_CODE_PRIORITY.items():
        code = next((candidate for candidate in priority if candidate in severities), None)
        if code is None:
            continue
        incidents.append(
            AlertIncident(
                alert_class=alert_class,
                code=code,
                severity=severities[code],
                release_id=release_id,
                observed_at=observed_at,
                fingerprint=_incident_fingerprint(alert_class, code, release_id),
            )
        )
    return tuple(incidents)


def _receipt_filename(alert_class: str) -> str:
    try:
        return _RECEIPT_FILENAMES[alert_class]
    except KeyError:
        raise ValueError("Unsupported operational alert class") from None


def _open_directory_path(path: Path) -> int:
    """Create and open one absolute directory without following symlink components."""

    path = Path(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path == Path(path.anchor)
    ):
        raise ValueError("Operational alert receipt directory must be absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError("Operational alert receipt directory is unsafe")
        os.fchmod(descriptor, 0o700)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _ensure_regular_destination(directory_descriptor: int, filename: str) -> None:
    try:
        metadata = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Operational alert receipt destination is unsafe")


def _strict_json_object(raw: bytes) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate receipt key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)


def _receipt_from_payload(payload: object, alert_class: str) -> DeliveryReceipt:
    if not isinstance(payload, dict) or set(payload) != _RECEIPT_KEYS:
        raise ValueError("Operational alert receipt is invalid")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Operational alert receipt is invalid")
    status_value = payload.get("status")
    if status_value not in {"delivered", "failed", "resolved"}:
        raise ValueError("Operational alert receipt is invalid")
    status: DeliveryStatus = status_value
    if payload.get("alert_class") != alert_class:
        raise ValueError("Operational alert receipt is invalid")
    observed_at = _canonical_timestamp(payload.get("observed_at"))
    release_id = _safe_release_id(payload.get("release_id"))
    code = payload.get("code")
    attempt_count = payload.get("attempt_count")
    delivered_at_value = payload.get("delivered_at")
    fingerprint = payload.get("fingerprint")
    http_status = payload.get("http_status")
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
        raise ValueError("Operational alert receipt is invalid")
    if http_status is not None and (
        isinstance(http_status, bool)
        or not isinstance(http_status, int)
        or not 100 <= http_status <= 599
    ):
        raise ValueError("Operational alert receipt is invalid")

    if status == "resolved":
        if (
            code != ""
            or attempt_count != 0
            or delivered_at_value is not None
            or fingerprint != ""
            or http_status is not None
        ):
            raise ValueError("Operational alert receipt is invalid")
        delivered_at = None
    else:
        if (
            not isinstance(code, str)
            or code not in SUPPORTED_ALERT_CLASSES[alert_class]
            or not 1 <= attempt_count <= 3
            or not isinstance(fingerprint, str)
            or not _FINGERPRINT.fullmatch(fingerprint)
        ):
            raise ValueError("Operational alert receipt is invalid")
        if status == "delivered":
            delivered_at = _canonical_timestamp(delivered_at_value)
            if http_status is None or not 200 <= http_status < 300:
                raise ValueError("Operational alert receipt is invalid")
        else:
            if delivered_at_value is not None:
                raise ValueError("Operational alert receipt is invalid")
            delivered_at = None

    return DeliveryReceipt(
        status=status,
        alert_class=alert_class,
        code=code,
        attempt_count=attempt_count,
        observed_at=observed_at,
        delivered_at=delivered_at,
        release_id=release_id,
        fingerprint=fingerprint,
        http_status=http_status,
    )


def _read_receipt(directory_descriptor: int, alert_class: str) -> DeliveryReceipt | None:
    filename = _receipt_filename(alert_class)
    _ensure_regular_destination(directory_descriptor, filename)
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_descriptor,
        )
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECEIPT_BYTES:
            return None
        raw = os.read(descriptor, MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            return None
        return _receipt_from_payload(_strict_json_object(raw), alert_class)
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _receipt_payload(receipt: DeliveryReceipt) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, **asdict(receipt)}


def _write_receipt(
    receipt_dir: Path,
    directory_descriptor: int,
    receipt: DeliveryReceipt,
) -> None:
    filename = _receipt_filename(receipt.alert_class)
    _ensure_regular_destination(directory_descriptor, filename)
    payload_bytes = (
        json.dumps(
            _receipt_payload(receipt),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")
    if len(payload_bytes) > MAX_RECEIPT_BYTES:
        raise ValueError("Operational alert receipt is too large")

    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_path_raw = tempfile.mkstemp(
            dir=receipt_dir,
            prefix=f".{filename}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_path_raw)
        temporary_name = temporary_path.name
        directory_metadata = os.fstat(directory_descriptor)
        parent_metadata = os.stat(temporary_path.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or (directory_metadata.st_dev, directory_metadata.st_ino)
            != (parent_metadata.st_dev, parent_metadata.st_ino)
            or not stat.S_ISREG(os.fstat(descriptor).st_mode)
        ):
            raise ValueError("Operational alert receipt directory is unsafe")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        temporary_name = None
        os.fsync(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass


def _now_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise ValueError("Operational alert clock is invalid")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _payload_for_incident(incident: AlertIncident) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "alert_class": incident.alert_class,
        "code": incident.code,
        "severity": incident.severity,
        "release_id": incident.release_id,
        "observed_at": incident.observed_at,
        "fingerprint": incident.fingerprint,
    }


class OperationalAlertDispatcher:
    """Deliver selected incidents without coupling webhook health to runtime health."""

    def __init__(
        self,
        config: AlertDeliveryConfig,
        *,
        receipt_dir: Path,
        session: _SessionLike | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.receipt_dir = Path(receipt_dir)
        if (
            not self.receipt_dir.is_absolute()
            or ".." in self.receipt_dir.parts
            or self.receipt_dir == Path(self.receipt_dir.anchor)
        ):
            raise ValueError("Operational alert receipt directory is unsafe")
        self.session = requests.Session() if session is None else session
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _deliver(self, incident: AlertIncident) -> DeliveryReceipt:
        headers = {
            "Content-Type": "application/json",
            **(
                {"Authorization": f"Bearer {self.config.bearer_token}"}
                if self.config.bearer_token
                else {}
            ),
        }
        payload = _payload_for_incident(incident)
        last_status: int | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = self.session.post(
                    self.config.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )
                raw_status = getattr(response, "status_code", None)
                last_status = (
                    raw_status
                    if isinstance(raw_status, int)
                    and not isinstance(raw_status, bool)
                    and 100 <= raw_status <= 599
                    else None
                )
            except requests.RequestException:
                last_status = None
            if last_status is not None and 200 <= last_status < 300:
                return DeliveryReceipt(
                    status="delivered",
                    alert_class=incident.alert_class,
                    code=incident.code,
                    attempt_count=attempt,
                    observed_at=incident.observed_at,
                    delivered_at=_now_timestamp(self.clock),
                    release_id=incident.release_id,
                    fingerprint=incident.fingerprint,
                    http_status=last_status,
                )
            if attempt < self.config.max_attempts:
                self.sleep(min(5.0, float(2 ** (attempt - 1))))
        return DeliveryReceipt(
            status="failed",
            alert_class=incident.alert_class,
            code=incident.code,
            attempt_count=self.config.max_attempts,
            observed_at=incident.observed_at,
            delivered_at=None,
            release_id=incident.release_id,
            fingerprint=incident.fingerprint,
            http_status=last_status,
        )

    def dispatch(self, snapshot: dict[str, Any]) -> tuple[DeliveryReceipt, ...]:
        incidents = incidents_from_snapshot(snapshot)
        release_id, observed_at = _snapshot_metadata(snapshot)
        by_class = {incident.alert_class: incident for incident in incidents}
        directory_descriptor = _open_directory_path(self.receipt_dir)
        receipts: list[DeliveryReceipt] = []
        try:
            with _PROCESS_LOCK:
                fcntl.flock(directory_descriptor, fcntl.LOCK_EX)
                try:
                    for alert_class in SUPPORTED_ALERT_CLASSES:
                        previous = _read_receipt(directory_descriptor, alert_class)
                        incident = by_class.get(alert_class)
                        if incident is None:
                            if previous is not None and previous.status == "resolved":
                                receipt = previous
                            else:
                                receipt = DeliveryReceipt(
                                    status="resolved",
                                    alert_class=alert_class,
                                    code="",
                                    attempt_count=0,
                                    observed_at=observed_at,
                                    delivered_at=None,
                                    release_id=release_id,
                                    fingerprint="",
                                    http_status=None,
                                )
                                _write_receipt(
                                    self.receipt_dir,
                                    directory_descriptor,
                                    receipt,
                                )
                        elif (
                            previous is not None
                            and previous.status == "delivered"
                            and previous.fingerprint == incident.fingerprint
                        ):
                            receipt = previous
                        else:
                            receipt = self._deliver(incident)
                            _write_receipt(
                                self.receipt_dir,
                                directory_descriptor,
                                receipt,
                            )
                        receipts.append(receipt)
                finally:
                    fcntl.flock(directory_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(directory_descriptor)
        return tuple(receipts)
