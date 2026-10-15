"""Durable job leases, cancellation, attempts and sanitized event logs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection
from app.database.user_repository import _resolve_owner_user_id_for_write, _seed_operator_user_from_env
from app.database.json_fields import decode_json_field as _decode_json_field
from app.jobs.states import normalize_job_state

def record_job_attempt(
    db_path: Path,
    job_id: str,
    chapter_id: int | None,
    provider_id: str,
    model: str,
    status: str,
    stage: str = "",
    error: str = "",
    elapsed_ms: int = 0,
    owner_user_id: str = "",
) -> int:
    resolved_owner_user_id = _resolve_owner_user_id_for_write(db_path, owner_user_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_attempts
            (job_id, chapter_id, owner_user_id, stage, provider_id, model, status, error, elapsed_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, chapter_id, resolved_owner_user_id, stage, provider_id, model, status, error, elapsed_ms),
        )
        conn.commit()
        return cur.lastrowid



def get_job_attempts(
    db_path: Path,
    job_id: str | None = None,
    chapter_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    clauses = []
    params: list[object] = []
    if job_id is not None:
        clauses.append("job_id = ?")
        params.append(job_id)
    if chapter_id is not None:
        clauses.append("chapter_id = ?")
        params.append(chapter_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(0, limit))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM job_attempts
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]



_JOB_LOG_SENSITIVE_MARKERS = (
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



MAX_JOB_LOG_MESSAGE_LENGTH = 500



MAX_JOB_LOG_DETAIL_VALUE_LENGTH = 500



MAX_JOB_LOG_LIMIT = 100



def _job_value_has_sensitive_marker(value: object) -> bool:
    return any(marker in str(value).lower() for marker in _JOB_LOG_SENSITIVE_MARKERS)



def _sanitize_job_log_message(message: str) -> str:
    if _job_value_has_sensitive_marker(message):
        return "Job event recorded. Check server logs."
    return str(message).replace("\n", " ").strip()[:MAX_JOB_LOG_MESSAGE_LENGTH]



def _sanitize_job_log_detail_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\n", " ").strip()[:MAX_JOB_LOG_DETAIL_VALUE_LENGTH]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered[:MAX_JOB_LOG_DETAIL_VALUE_LENGTH]



def _sanitize_job_log_details(details: dict[str, Any] | None) -> dict[str, Any]:
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        key_text = str(key)
        lowered_key = key_text.lower()
        if any(marker in lowered_key for marker in ("secret", "key", "token", "password", "authorization")):
            safe_details[key_text] = "[redacted]"
        elif _job_value_has_sensitive_marker(value):
            safe_details[key_text] = "[redacted]"
        else:
            safe_details[key_text] = _sanitize_job_log_detail_value(value)
    return safe_details



def sanitize_job_error(message: str) -> str:
    if not message:
        return ""
    if _job_value_has_sensitive_marker(message):
        return "Job failed. Check server logs."
    return str(message).replace("\n", " ").strip()[:500]



def _mobile_job_from_row(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["target_ids"] = _decode_json_field(job.pop("target_ids_json", None), [])
    job["params"] = _decode_json_field(job.pop("params_json", None), {})
    job["state"] = normalize_job_state(
        str(job.get("status") or ""),
        current_step=str(job.get("current_step") or ""),
        existing_state=str(job.get("state") or ""),
    )
    job["cancel_requested"] = bool(int(job.get("cancel_requested") or 0))
    return job



def save_mobile_job(db_path: Path, job: dict) -> None:
    target_ids_json = json.dumps(job.get("target_ids", []), ensure_ascii=False)
    params_json = json.dumps(job.get("params", {}), ensure_ascii=False)
    status = str(job.get("status") or "queued")
    current_step = str(job.get("current_step") or "")
    state = normalize_job_state(status, current_step=current_step, existing_state=str(job.get("state") or ""))
    retry_count = int(job.get("retry_count") or (job.get("params") or {}).get("retry_count") or 0)
    with get_connection(db_path) as conn:
        owner_user_id = str(job.get("owner_user_id") or "").strip()
        if not owner_user_id:
            row = conn.execute(
                "SELECT owner_user_id FROM mobile_jobs WHERE job_id = ?",
                (job["job_id"],),
            ).fetchone()
            owner_user_id = str(row["owner_user_id"] or "") if row else ""
        if not owner_user_id:
            owner_user_id = str(_seed_operator_user_from_env(conn).get("id") or "")
        conn.execute(
            """
            INSERT INTO mobile_jobs
            (
                job_id, job_type, owner_user_id, status, state, progress, total,
                current_book_id, current_chapter_id, current_chunk_index, total_chunks,
                current_step, provider, model, retry_count, target_ids_json, params_json,
                message, error, created_at, updated_at, started_at, completed_at, failed_at,
                finished_at, cancel_requested, last_safe_error, internal_error_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_type = excluded.job_type,
                owner_user_id = excluded.owner_user_id,
                status = excluded.status,
                state = excluded.state,
                progress = excluded.progress,
                total = excluded.total,
                current_book_id = excluded.current_book_id,
                current_chapter_id = excluded.current_chapter_id,
                current_chunk_index = excluded.current_chunk_index,
                total_chunks = excluded.total_chunks,
                current_step = excluded.current_step,
                provider = excluded.provider,
                model = excluded.model,
                retry_count = excluded.retry_count,
                target_ids_json = excluded.target_ids_json,
                params_json = excluded.params_json,
                message = excluded.message,
                error = excluded.error,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at,
                failed_at = excluded.failed_at,
                finished_at = excluded.finished_at,
                cancel_requested = excluded.cancel_requested,
                last_safe_error = excluded.last_safe_error,
                internal_error_ref = excluded.internal_error_ref
            """,
            (
                job["job_id"],
                job["job_type"],
                owner_user_id,
                status,
                state,
                int(job.get("progress", 0)),
                int(job.get("total", 0)),
                int(job.get("current_book_id") or 0),
                int(job.get("current_chapter_id") or 0),
                int(job.get("current_chunk_index") or 0),
                int(job.get("total_chunks") or 0),
                current_step,
                str(job.get("provider") or ""),
                str(job.get("model") or ""),
                retry_count,
                target_ids_json,
                params_json,
                job.get("message", ""),
                job.get("error", ""),
                job.get("created_at", ""),
                job.get("updated_at", ""),
                job.get("started_at", ""),
                job.get("completed_at", ""),
                job.get("failed_at", ""),
                job.get("finished_at"),
                1 if job.get("cancel_requested") else 0,
                str(job.get("last_safe_error") or ""),
                str(job.get("internal_error_ref") or ""),
            ),
        )
        conn.commit()



def get_mobile_job(db_path: Path, job_id: str) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM mobile_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _mobile_job_from_row(row) if row else None



def list_mobile_jobs(db_path: Path, limit: int = 50) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM mobile_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, limit),),
        ).fetchall()
        return [_mobile_job_from_row(row) for row in rows]



def claim_mobile_job(
    db_path: Path,
    *,
    job_id: str,
    worker_id: str,
    lease_token: str,
    lease_seconds: int = 120,
) -> bool:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'running',
                state = 'CLAIMED',
                current_step = 'CLAIMED',
                lease_token = ?,
                lease_owner = ?,
                lease_expires_at = ?,
                heartbeat_at = ?,
                updated_at = ?,
                started_at = CASE WHEN COALESCE(started_at, '') = '' THEN ? ELSE started_at END
            WHERE job_id = ?
              AND status IN ('queued', 'retrying', 'pending')
              AND COALESCE(lease_token, '') = ''
            """,
            (lease_token, worker_id, expires_at, now_text, now_text, now_text, job_id),
        )
        conn.commit()
        return cur.rowcount == 1



def heartbeat_mobile_job_lease(
    db_path: Path,
    *,
    job_id: str,
    lease_token: str,
    lease_seconds: int = 120,
) -> bool:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    expires_at = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = ?
              AND lease_token = ?
              AND status = 'running'
            """,
            (now_text, expires_at, now_text, job_id, lease_token),
        )
        conn.commit()
        return cur.rowcount == 1



def release_mobile_job_lease(db_path: Path, *, job_id: str, lease_token: str) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET lease_token = '',
                lease_owner = '',
                lease_expires_at = '',
                heartbeat_at = ''
            WHERE job_id = ?
              AND lease_token = ?
            """,
            (job_id, lease_token),
        )
        conn.commit()
        return cur.rowcount == 1



def mark_interrupted_mobile_jobs(
    db_path: Path,
    *,
    stale_after_seconds: int = 300,
    include_queued: bool = True,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=max(1, stale_after_seconds))).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE mobile_jobs
            SET status = 'interrupted',
                state = 'STALE_INTERRUPTED',
                message = 'Job interrupted before completion. Please retry the job.',
                error = 'Job interrupted before completion',
                last_safe_error = 'Job interrupted before completion',
                updated_at = ?,
                finished_at = ?,
                lease_token = '',
                lease_owner = '',
                lease_expires_at = '',
                heartbeat_at = ''
            WHERE (
                    ? = 1
                    AND status IN ('pending', 'queued', 'retrying')
                    AND COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), '') <= ?
               )
               OR (
                    status = 'running'
                    AND (
                        (
                            COALESCE(lease_token, '') = ''
                            AND COALESCE(NULLIF(updated_at, ''), NULLIF(created_at, ''), '') <= ?
                        )
                        OR (
                            COALESCE(lease_token, '') != ''
                            AND (
                                COALESCE(lease_expires_at, '') = ''
                                OR lease_expires_at <= ?
                                OR COALESCE(heartbeat_at, '') = ''
                                OR heartbeat_at <= ?
                            )
                        )
                    )
               )
            """,
            (now, now, 1 if include_queued else 0, stale_before, stale_before, now, stale_before),
        )
        conn.commit()
        return cur.rowcount



def count_mobile_jobs_by_status(db_path: Path) -> dict[str, int]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM mobile_jobs
            GROUP BY status
            """
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}



def request_cancel_mobile_job(db_path: Path, *, job_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT status FROM mobile_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return False
        status = str(row["status"] or "").lower()
        if status in {"completed", "failed", "cancelled", "canceled", "interrupted"}:
            return True
        if status in {"pending", "queued", "retrying"}:
            cur = conn.execute(
                """
                UPDATE mobile_jobs
                SET cancel_requested = 1,
                    status = 'cancelled',
                    state = 'CANCELED',
                    message = 'Job cancelled before claim',
                    updated_at = ?,
                    finished_at = ?
                WHERE job_id = ?
                """,
                (now, now, job_id),
            )
        else:
            cur = conn.execute(
                """
                UPDATE mobile_jobs
                SET cancel_requested = 1,
                    message = 'Cancel requested',
                    updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )
        conn.commit()
        return cur.rowcount > 0



def record_job_log(
    db_path: Path,
    *,
    job_id: str,
    event_type: str,
    state: str = "",
    step: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> int:
    safe_message = _sanitize_job_log_message(message)
    safe_details = _sanitize_job_log_details(details)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO job_logs
            (job_id, event_type, state, step, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event_type,
                state,
                step,
                safe_message,
                json.dumps(safe_details, ensure_ascii=False),
            ),
        )
        conn.commit()
        return cur.lastrowid



def get_job_logs(db_path: Path, job_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    safe_limit = min(MAX_JOB_LOG_LIMIT, max(0, int(limit)))
    safe_offset = max(0, int(offset))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM job_logs
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            OFFSET ?
            """,
            (job_id, safe_limit, safe_offset),
        ).fetchall()
    logs: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["details"] = _decode_json_field(item.pop("details_json", None), {})
        logs.append(item)
    return logs

