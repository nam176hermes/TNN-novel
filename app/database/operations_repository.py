from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection


@dataclass(frozen=True)
class RetentionPolicy:
    """Age and row-count bounds supplied by the retention service layer."""

    max_age_days: int
    max_rows: int

    def __post_init__(self) -> None:
        if self.max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        if self.max_rows <= 0:
            raise ValueError("max_rows must be positive")


_OPERATIONAL_SENSITIVE_MARKERS = (
    "\n",
    "traceback",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "bearer ",
    "token",
    "/tmp/",
    "/home/",
    "\\users\\",
    "sk-",
)


def _operational_value_has_sensitive_marker(value: object) -> bool:
    return any(marker in str(value).lower() for marker in _OPERATIONAL_SENSITIVE_MARKERS)


def _sanitize_operational_message(message: str) -> str:
    if _operational_value_has_sensitive_marker(message):
        return "Operational event recorded. Check server logs."
    return message


def _sanitize_operational_details(details: dict[str, Any] | None) -> dict[str, Any]:
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        key_text = str(key)
        lowered_key = key_text.lower()
        if any(marker in lowered_key for marker in ("secret", "key", "token", "password", "authorization")):
            safe_details[key_text] = "[redacted]"
        elif _operational_value_has_sensitive_marker(value):
            safe_details[key_text] = "[redacted]"
        else:
            safe_details[key_text] = value
    return safe_details


def _decode_json_field(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def record_operational_event(
    db_path: Path,
    *,
    event_type: str,
    severity: str = "info",
    source: str = "",
    message: str = "",
    job_id: str = "",
    details: dict[str, Any] | None = None,
    actor_user_id: str = "",
    owner_user_id: str = "",
) -> int:
    safe_message = _sanitize_operational_message(message)
    safe_details = _sanitize_operational_details(details)
    safe_actor_user_id = "" if _operational_value_has_sensitive_marker(actor_user_id) else actor_user_id
    safe_owner_user_id = "" if _operational_value_has_sensitive_marker(owner_user_id) else owner_user_id
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO operational_events
            (
                event_type, severity, source, message,
                actor_user_id, owner_user_id, details_json, job_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                severity,
                source,
                safe_message,
                safe_actor_user_id,
                safe_owner_user_id,
                json.dumps(safe_details, ensure_ascii=False),
                job_id,
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_operational_events(
    db_path: Path,
    *,
    limit: int = 20,
    severities: tuple[str, ...] = ("error", "warning"),
) -> list[dict[str, Any]]:
    params: list[object] = []
    where = ""
    if severities:
        placeholders = ", ".join("?" for _ in severities)
        where = f"WHERE severity IN ({placeholders})"
        params.extend(severities)
    params.append(max(0, limit))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM operational_events
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        event["details"] = _decode_json_field(event.pop("details_json", None), {})
        events.append(event)
    return events


def _delete_event_ids(conn: Any, event_ids: list[int]) -> int:
    if not event_ids:
        return 0
    placeholders = ", ".join("?" for _ in event_ids)
    cur = conn.execute(
        f"DELETE FROM operational_events WHERE id IN ({placeholders})",
        event_ids,
    )
    return int(cur.rowcount)


def prune_operational_events(
    db_path: Path,
    *,
    policy: RetentionPolicy,
    batch_size: int,
    reserved_rows: int = 0,
    now: str | None = None,
) -> int:
    """Delete one deterministic, age-first operational-event batch."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if reserved_rows < 0:
        raise ValueError("reserved_rows cannot be negative")

    comparison_time = now or datetime.now(timezone.utc).isoformat()
    age_modifier = f"-{policy.max_age_days} days"
    effective_max_rows = max(0, policy.max_rows - reserved_rows)
    deleted = 0

    with get_connection(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            age_rows = conn.execute(
                """
                SELECT id
                FROM operational_events
                WHERE julianday(created_at) < julianday(?, ?)
                ORDER BY julianday(created_at) ASC, id ASC
                LIMIT ?
                """,
                (comparison_time, age_modifier, batch_size),
            ).fetchall()
            deleted += _delete_event_ids(conn, [int(row["id"]) for row in age_rows])

            remaining = batch_size - deleted
            if remaining > 0:
                row = conn.execute("SELECT COUNT(*) AS row_count FROM operational_events").fetchone()
                overflow = max(0, int(row["row_count"] if row else 0) - effective_max_rows)
                if overflow:
                    count_rows = conn.execute(
                        """
                        SELECT id
                        FROM operational_events
                        ORDER BY julianday(created_at) ASC, id ASC
                        LIMIT ?
                        """,
                        (min(remaining, overflow),),
                    ).fetchall()
                    deleted += _delete_event_ids(conn, [int(row["id"]) for row in count_rows])
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return deleted
