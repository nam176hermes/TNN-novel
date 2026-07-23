from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection
from app.database.operations_repository import RetentionPolicy


def _utcnow_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_auth_session(
    db_path: Path,
    *,
    session_id: str,
    username: str,
    user_id: str = "",
    refresh_token_hash: str,
    refresh_family_id: str,
    expires_at: str,
    client_host: str = "",
    user_agent: str = "",
    request_id: str = "",
) -> None:
    now = _utcnow_text()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
            (
                session_id, username, user_id, refresh_token_hash, refresh_family_id,
                created_at, expires_at, revoked_at, last_seen_at,
                client_host, user_agent, request_id, reuse_detected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, '')
            """,
            (
                session_id,
                username,
                user_id,
                refresh_token_hash,
                refresh_family_id,
                now,
                expires_at,
                now,
                client_host,
                user_agent,
                request_id,
            ),
        )
        conn.commit()


def get_auth_session(db_path: Path, session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM auth_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def touch_auth_session(db_path: Path, session_id: str) -> None:
    if not session_id:
        return
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE auth_sessions
            SET last_seen_at = ?
            WHERE session_id = ? AND COALESCE(revoked_at, '') = ''
            """,
            (_utcnow_text(), session_id),
        )
        conn.commit()


def auth_session_is_active(session: dict[str, Any] | None, *, username: str = "") -> bool:
    if not session:
        return False
    if username and session.get("username") != username:
        return False
    if session.get("revoked_at"):
        return False
    expires_at = str(session.get("expires_at") or "")
    return bool(expires_at and expires_at > _utcnow_text())


def revoke_auth_session(db_path: Path, session_id: str) -> int:
    if not session_id:
        return 0
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = ?
            WHERE session_id = ? AND COALESCE(revoked_at, '') = ''
            """,
            (_utcnow_text(), session_id),
        )
        conn.commit()
        return cur.rowcount


def revoke_auth_sessions_for_username(db_path: Path, username: str) -> int:
    if not username:
        return 0
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = ?
            WHERE username = ? AND COALESCE(revoked_at, '') = ''
            """,
            (_utcnow_text(), username),
        )
        conn.commit()
        return cur.rowcount


def rotate_auth_session_refresh(
    db_path: Path,
    *,
    session_id: str,
    current_refresh_token_hash: str,
    next_refresh_token_hash: str,
    next_expires_at: str,
) -> tuple[str, dict[str, Any] | None]:
    """Rotate a refresh token hash for a session.

    Returns a status string: rotated, unknown, revoked, expired, or reuse_detected.
    """
    if not session_id:
        return "unknown", None
    now = _utcnow_text()
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM auth_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return "unknown", None

        session = dict(row)
        if session.get("revoked_at"):
            return "revoked", session
        if str(session.get("expires_at") or "") <= now:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()
            session["revoked_at"] = now
            return "expired", session
        if session.get("refresh_token_hash") != current_refresh_token_hash:
            conn.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?, reuse_detected_at = ?
                WHERE session_id = ? AND COALESCE(revoked_at, '') = ''
                """,
                (now, now, session_id),
            )
            conn.commit()
            session["revoked_at"] = now
            session["reuse_detected_at"] = now
            return "reuse_detected", session

        conn.execute(
            """
            UPDATE auth_sessions
            SET refresh_token_hash = ?, expires_at = ?, last_seen_at = ?
            WHERE session_id = ? AND COALESCE(revoked_at, '') = ''
            """,
            (next_refresh_token_hash, next_expires_at, now, session_id),
        )
        conn.commit()
        session["refresh_token_hash"] = next_refresh_token_hash
        session["expires_at"] = next_expires_at
        session["last_seen_at"] = now
        return "rotated", session


def record_auth_login_failure(
    db_path: Path,
    *,
    rate_limit_key: str,
    username: str,
    client_host: str = "",
    failed_at: str | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_login_failures (rate_limit_key, username, client_host, failed_at)
            VALUES (?, ?, ?, ?)
            """,
            (rate_limit_key, username, client_host, failed_at or _utcnow_text()),
        )
        conn.commit()


def count_auth_login_failures(db_path: Path, *, rate_limit_key: str, since: str) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS failure_count
            FROM auth_login_failures
            WHERE rate_limit_key = ? AND failed_at > ?
            """,
            (rate_limit_key, since),
        ).fetchone()
    return int(row["failure_count"] if row else 0)


def clear_auth_login_failures(db_path: Path, *, rate_limit_key: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM auth_login_failures WHERE rate_limit_key = ?", (rate_limit_key,))
        conn.commit()


_SESSION_RETENTION_TIME = (
    "CASE WHEN COALESCE(revoked_at, '') <> '' THEN revoked_at ELSE expires_at END"
)
_SESSION_RETENTION_ELIGIBLE = (
    "(COALESCE(revoked_at, '') <> '' OR julianday(expires_at) <= julianday(?))"
)


def _delete_primary_keys(
    conn: Any,
    *,
    table: str,
    primary_key: str,
    keys: list[object],
) -> int:
    if not keys:
        return 0
    placeholders = ", ".join("?" for _ in keys)
    cur = conn.execute(
        f"DELETE FROM {table} WHERE {primary_key} IN ({placeholders})",
        keys,
    )
    return int(cur.rowcount)


def prune_auth_records(
    db_path: Path,
    *,
    session_policy: RetentionPolicy,
    login_failure_policy: RetentionPolicy,
    batch_size: int,
    now: str | None = None,
) -> dict[str, int]:
    """Delete one shared, deterministic, age-first batch of inactive auth data."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    comparison_time = now or _utcnow_text()
    session_age_modifier = f"-{session_policy.max_age_days} days"
    failure_age_modifier = f"-{login_failure_policy.max_age_days} days"
    deleted = {"auth_sessions": 0, "auth_login_failures": 0}

    with get_connection(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            session_age_rows = conn.execute(
                f"""
                SELECT session_id
                FROM auth_sessions
                WHERE {_SESSION_RETENTION_ELIGIBLE}
                  AND julianday({_SESSION_RETENTION_TIME}) < julianday(?, ?)
                ORDER BY julianday({_SESSION_RETENTION_TIME}) ASC, session_id ASC
                LIMIT ?
                """,
                (comparison_time, comparison_time, session_age_modifier, batch_size),
            ).fetchall()
            deleted["auth_sessions"] += _delete_primary_keys(
                conn,
                table="auth_sessions",
                primary_key="session_id",
                keys=[str(row["session_id"]) for row in session_age_rows],
            )

            remaining = batch_size - sum(deleted.values())
            if remaining > 0:
                failure_age_rows = conn.execute(
                    """
                    SELECT id
                    FROM auth_login_failures
                    WHERE julianday(failed_at) < julianday(?, ?)
                    ORDER BY julianday(failed_at) ASC, id ASC
                    LIMIT ?
                    """,
                    (comparison_time, failure_age_modifier, remaining),
                ).fetchall()
                deleted["auth_login_failures"] += _delete_primary_keys(
                    conn,
                    table="auth_login_failures",
                    primary_key="id",
                    keys=[int(row["id"]) for row in failure_age_rows],
                )

            remaining = batch_size - sum(deleted.values())
            if remaining > 0:
                session_count_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS row_count
                    FROM auth_sessions
                    WHERE {_SESSION_RETENTION_ELIGIBLE}
                    """,
                    (comparison_time,),
                ).fetchone()
                session_overflow = max(
                    0,
                    int(session_count_row["row_count"] if session_count_row else 0)
                    - session_policy.max_rows,
                )
                if session_overflow:
                    session_count_rows = conn.execute(
                        f"""
                        SELECT session_id
                        FROM auth_sessions
                        WHERE {_SESSION_RETENTION_ELIGIBLE}
                        ORDER BY julianday({_SESSION_RETENTION_TIME}) ASC, session_id ASC
                        LIMIT ?
                        """,
                        (comparison_time, min(remaining, session_overflow)),
                    ).fetchall()
                    deleted["auth_sessions"] += _delete_primary_keys(
                        conn,
                        table="auth_sessions",
                        primary_key="session_id",
                        keys=[str(row["session_id"]) for row in session_count_rows],
                    )

            remaining = batch_size - sum(deleted.values())
            if remaining > 0:
                failure_count_row = conn.execute(
                    "SELECT COUNT(*) AS row_count FROM auth_login_failures"
                ).fetchone()
                failure_overflow = max(
                    0,
                    int(failure_count_row["row_count"] if failure_count_row else 0)
                    - login_failure_policy.max_rows,
                )
                if failure_overflow:
                    failure_count_rows = conn.execute(
                        """
                        SELECT id
                        FROM auth_login_failures
                        ORDER BY julianday(failed_at) ASC, id ASC
                        LIMIT ?
                        """,
                        (min(remaining, failure_overflow),),
                    ).fetchall()
                    deleted["auth_login_failures"] += _delete_primary_keys(
                        conn,
                        table="auth_login_failures",
                        primary_key="id",
                        keys=[int(row["id"]) for row in failure_count_rows],
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return deleted


def get_auth_session_retention_report(
    db_path: Path,
    *,
    session_policy: RetentionPolicy,
    now: str | None = None,
) -> dict[str, int]:
    """Return a read-only session classification and eventual prune estimate."""
    comparison_time = now or _utcnow_text()
    age_modifier = f"-{session_policy.max_age_days} days"
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE
                    WHEN COALESCE(revoked_at, '') = ''
                     AND julianday(expires_at) > julianday(?) THEN 1 ELSE 0 END
                ) AS active,
                SUM(CASE
                    WHEN COALESCE(revoked_at, '') = ''
                     AND julianday(expires_at) <= julianday(?) THEN 1 ELSE 0 END
                ) AS expired,
                SUM(CASE WHEN COALESCE(revoked_at, '') <> '' THEN 1 ELSE 0 END) AS revoked
            FROM auth_sessions
            """,
            (comparison_time, comparison_time),
        ).fetchone()
        age_eligible_row = conn.execute(
            f"""
            SELECT COUNT(*) AS row_count
            FROM auth_sessions
            WHERE {_SESSION_RETENTION_ELIGIBLE}
              AND julianday({_SESSION_RETENTION_TIME}) < julianday(?, ?)
            """,
            (comparison_time, comparison_time, age_modifier),
        ).fetchone()

    total = int(row["total"] if row else 0)
    active = int((row["active"] if row else 0) or 0)
    expired = int((row["expired"] if row else 0) or 0)
    revoked = int((row["revoked"] if row else 0) or 0)
    age_eligible = int(age_eligible_row["row_count"] if age_eligible_row else 0)
    inactive_after_age = max(0, expired + revoked - age_eligible)
    row_cap_eligible = max(0, inactive_after_age - session_policy.max_rows)
    return {
        "total": total,
        "active": active,
        "expired": expired,
        "revoked": revoked,
        "age_eligible": age_eligible,
        "row_cap_eligible": row_cap_eligible,
        "would_remove": age_eligible + row_cap_eligible,
    }
