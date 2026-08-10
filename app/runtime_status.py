"""Read-only runtime status shared by readiness and authenticated operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from app.runtime_identity import RuntimeIdentity


WORKER_HEARTBEAT_RELATIVE_PATH = Path("logs/runtime/import-worker.heartbeat")


@dataclass(frozen=True)
class WorkerRuntimeStatus:
    status: str
    required: bool
    heartbeat_age_seconds: float | None
    release_id: str
    release_match: bool
    queue_claim_capable: bool
    reason: str

    def safe_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_heartbeat(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("heartbeat payload is not an object")
    return payload


def inspect_worker_runtime(
    *,
    data_dir: Path,
    db_path: Path | str,
    db_uri: bool = False,
    api_identity: RuntimeIdentity,
    required: bool,
    max_age_seconds: float,
    now: float | None = None,
) -> WorkerRuntimeStatus:
    """Inspect the safe heartbeat contract without returning paths or worker IDs."""

    if not required:
        return WorkerRuntimeStatus(
            status="in_process",
            required=False,
            heartbeat_age_seconds=0.0,
            release_id=api_identity.release_id,
            release_match=True,
            queue_claim_capable=True,
            reason="api_owns_import_jobs",
        )

    heartbeat_path = data_dir / WORKER_HEARTBEAT_RELATIVE_PATH
    try:
        heartbeat = _read_heartbeat(heartbeat_path)
        updated_at = float(heartbeat["updated_at"])
        release_id = str(heartbeat.get("release_id") or "unknown")[:192]
        component = str(heartbeat.get("component") or "")
        with sqlite3.connect(str(db_path), uri=db_uri) as connection:
            connection.execute("SELECT 1 FROM import_jobs LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM chapter_tasks LIMIT 1").fetchone()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, sqlite3.Error):
        return WorkerRuntimeStatus(
            status="missing",
            required=True,
            heartbeat_age_seconds=None,
            release_id="unknown",
            release_match=False,
            queue_claim_capable=False,
            reason="heartbeat_or_queue_unavailable",
        )

    age = max(0.0, (time.time() if now is None else now) - updated_at)
    release_match = release_id == api_identity.release_id and component == "import-worker"
    fresh = age <= max(0.0, max_age_seconds)
    if not fresh:
        status, reason = "stale", "heartbeat_stale"
    elif not release_match:
        status, reason = "release_mismatch", "release_mismatch"
    else:
        status, reason = "ready", "ready"
    capable = fresh and release_match
    return WorkerRuntimeStatus(
        status=status,
        required=True,
        heartbeat_age_seconds=round(age, 3),
        release_id=release_id,
        release_match=release_match,
        queue_claim_capable=capable,
        reason=reason,
    )
