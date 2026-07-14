from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection


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
