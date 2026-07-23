"""Authenticated, low-cardinality operational metrics and alert evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any

from app.config import settings
from app.mobile_api.config import mobile_settings
from app.runtime_identity import get_runtime_identity
from app.runtime_status import inspect_worker_runtime
from app.services.tts.availability import inspect_tts_capability
from app.storage.artifact_paths import APPROVED_PATH_FIELDS, ResolutionStatus, resolve_artifact_path
from scripts import ops


RESTORE_STATUS_RELATIVE_PATH = Path("logs/runtime/restore-drill.status.json")


def _age_seconds(value: str, *, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds()), 3)


def _optional_non_negative_int(name: str) -> int | None:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _artifact_snapshot(connection: sqlite3.Connection, data_dir: Path) -> dict[str, Any]:
    scanned = 0
    errors: dict[str, int] = {}
    for field in APPROVED_PATH_FIELDS:
        rows = connection.execute(
            f"SELECT {field.column} FROM {field.table} "
            f"WHERE {field.active_where} AND COALESCE({field.column}, '') <> ''"
        ).fetchall()
        for row in rows:
            scanned += 1
            result = resolve_artifact_path(
                row[0],
                artifact_class=field.artifact_class,
                data_root=data_dir,
                old_root=settings.artifact_legacy_root,
                require_exists=True,
            )
            if result.status not in {ResolutionStatus.CURRENT, ResolutionStatus.REMAPPED}:
                key = result.status.value
                errors[key] = errors.get(key, 0) + 1
    return {
        "status": "ok" if not errors else "error",
        "scanned": scanned,
        "error_count": sum(errors.values()),
        "errors_by_status": errors,
    }


def _restore_snapshot(data_dir: Path, *, now: datetime) -> dict[str, Any]:
    path = data_dir / RESTORE_STATUS_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status") or "unknown")
        completed_at = str(payload.get("completed_at") or "")
        age = _age_seconds(completed_at, now=now)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "not_recorded", "age_seconds": None}
    if status not in {"passed", "failed"}:
        status = "unknown"
    return {"status": status, "age_seconds": age}


def evaluate_operational_alerts(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate deterministic, low-cardinality alert rules."""

    alerts: list[dict[str, str]] = []

    def add(code: str, severity: str, message: str) -> None:
        alerts.append({"code": code, "severity": severity, "message": message})

    worker = snapshot["worker"]
    if worker["required"] and not worker["queue_claim_capable"]:
        add("worker_not_ready", "critical", "Required import worker cannot claim queued work")
    if snapshot["release"]["worker_match"] is False:
        add("release_mismatch", "critical", "API and worker release identities differ")
    if snapshot["storage"]["disk_free_bytes"] < 100 * 1024 * 1024:
        add("disk_critical", "critical", "Free disk space is below the required floor")
    elif snapshot["storage"]["disk_free_bytes"] < 1024 * 1024 * 1024:
        add("disk_low", "warning", "Free disk space is below the warning floor")
    oldest = snapshot["queue"]["oldest_age_seconds"]
    if oldest is not None and oldest > 3600:
        add("queue_stale", "warning", "Oldest queued work exceeds one hour")
    if snapshot["jobs"]["failed_or_interrupted"] > 0:
        add("jobs_failed", "warning", "Failed or interrupted jobs require review")
    backup_age = snapshot["backup"]["latest_age_seconds"]
    if backup_age is None or backup_age > 2 * 86400:
        add("backup_stale", "warning", "No recent validated system backup is recorded")
    drill_age = snapshot["restore_drill"]["age_seconds"]
    if snapshot["restore_drill"]["status"] != "passed" or drill_age is None or drill_age > 8 * 86400:
        add("restore_drill_stale", "warning", "No recent successful restore drill is recorded")
    if snapshot["artifacts"]["error_count"] > 0:
        add("artifact_integrity", "critical", "Artifact integrity scan found unavailable files")
    return alerts


@dataclass
class OperationalMetricsService:
    db_path: Path
    data_dir: Path
    cache_ttl_seconds: float = 30.0

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.data_dir = Path(self.data_dir)
        self._cached: tuple[float, dict[str, Any]] | None = None

    def snapshot(self, *, now: datetime | None = None, use_cache: bool = True) -> dict[str, Any]:
        monotonic_now = time.monotonic()
        if use_cache and self._cached and monotonic_now - self._cached[0] <= self.cache_ttl_seconds:
            return self._cached[1]
        resolved_now = now or datetime.now(timezone.utc)
        identity = get_runtime_identity(component="api")
        worker = inspect_worker_runtime(
            data_dir=self.data_dir,
            db_path=self.db_path,
            api_identity=identity,
            required=not mobile_settings.import_job_run_in_api,
            max_age_seconds=mobile_settings.import_worker_heartbeat_max_age_seconds,
            now=resolved_now.timestamp(),
        )
        with sqlite3.connect(str(self.db_path)) as connection:
            queued = connection.execute(
                """
                SELECT COUNT(*) FROM mobile_jobs
                WHERE lower(status) IN ('queued', 'pending', 'retrying')
                """
            ).fetchone()[0]
            queued += connection.execute(
                "SELECT COUNT(*) FROM chapter_tasks WHERE status IN ('queued', 'waiting_retry')"
            ).fetchone()[0]
            oldest_row = connection.execute(
                """
                SELECT MIN(created_at) FROM (
                    SELECT created_at FROM mobile_jobs WHERE lower(status) IN ('queued', 'pending', 'retrying')
                    UNION ALL
                    SELECT created_at FROM import_jobs WHERE status = 'queued'
                )
                """
            ).fetchone()
            failed = connection.execute(
                "SELECT COUNT(*) FROM mobile_jobs WHERE lower(status) IN ('failed', 'interrupted')"
            ).fetchone()[0]
            failed += connection.execute(
                "SELECT COUNT(*) FROM import_jobs WHERE status = 'failed'"
            ).fetchone()[0]
            auth = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN COALESCE(revoked_at, '') = '' AND julianday(expires_at) > julianday('now') THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN COALESCE(revoked_at, '') = '' AND julianday(expires_at) <= julianday('now') THEN 1 ELSE 0 END) AS expired,
                       SUM(CASE WHEN COALESCE(revoked_at, '') <> '' THEN 1 ELSE 0 END) AS revoked
                FROM auth_sessions
                """
            ).fetchone()
            artifacts = _artifact_snapshot(connection, self.data_dir)

        oldest_age = _age_seconds(oldest_row[0], now=resolved_now) if oldest_row and oldest_row[0] else None
        backups = [item for item in ops.list_backups(self.data_dir / "backups") if item.get("metadata_status") == "READY"]
        backup_ages = [
            age for age in (_age_seconds(str(item.get("created_at") or ""), now=resolved_now) for item in backups)
            if age is not None
        ]
        tts = inspect_tts_capability().safe_dict()
        disk_free = shutil.disk_usage(self.data_dir).free
        worker_payload = worker.safe_dict()
        snapshot: dict[str, Any] = {
            "generated_at": resolved_now.isoformat(),
            "api": {"health": "ok", "public_health": "external_probe_required"},
            "release": {
                "release_id": identity.release_id,
                "git_sha": identity.git_sha,
                "image_digest": identity.image_digest,
                "worker_match": worker.release_match,
            },
            "worker": worker_payload,
            "queue": {"depth": int(queued), "oldest_age_seconds": oldest_age},
            "jobs": {"failed_or_interrupted": int(failed)},
            "backup": {
                "ready_count": len(backups),
                "latest_age_seconds": min(backup_ages) if backup_ages else None,
            },
            "restore_drill": _restore_snapshot(self.data_dir, now=resolved_now),
            "storage": {
                "disk_free_bytes": int(disk_free),
                "database_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            },
            "artifacts": artifacts,
            "auth_sessions": {
                "total": int(auth[0] or 0),
                "active": int(auth[1] or 0),
                "expired": int(auth[2] or 0),
                "revoked": int(auth[3] or 0),
            },
            "tts": tts,
            "container": {"restart_count": _optional_non_negative_int("NOVEL_CONTAINER_RESTART_COUNT")},
        }
        snapshot["alerts"] = evaluate_operational_alerts(snapshot)
        self._cached = (monotonic_now, snapshot)
        return snapshot
