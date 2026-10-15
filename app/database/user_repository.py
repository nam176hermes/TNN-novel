"""Operator identity and ownership, including the existing idempotent user seed."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.database.auth_repository import _utcnow_text
from app.database.connection import get_connection
from app.database.schema_utils import _add_column_if_missing

def _ensure_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT DEFAULT '',
            source TEXT NOT NULL DEFAULT 'env',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disabled_at TEXT DEFAULT ''
        )
        """
    )
    _add_column_if_missing(conn, "users", "username TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "display_name TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "source TEXT DEFAULT 'env'")
    _add_column_if_missing(conn, "users", "created_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "updated_at TEXT DEFAULT ''")
    _add_column_if_missing(conn, "users", "disabled_at TEXT DEFAULT ''")



def _normalize_operator_username(username: str | None = None) -> str:
    value = (username if username is not None else os.getenv("MOBILE_API_ADMIN_USERNAME", "admin")).strip()
    return value or "admin"



def _stable_operator_user_id(username: str) -> str:
    normalized = username.strip().lower()
    digest = hashlib.sha256(f"novel-pipeline:env-operator:{normalized}".encode("utf-8")).hexdigest()
    return f"usr_{digest[:32]}"



def _seed_operator_user(conn: sqlite3.Connection, username: str | None = None) -> dict[str, Any]:
    _ensure_users_table(conn)
    resolved_username = _normalize_operator_username(username)
    now = _utcnow_text()
    existing = conn.execute(
        """
        SELECT * FROM users
        WHERE source = 'env'
        ORDER BY created_at, id
        LIMIT 1
        """
    ).fetchone()

    if existing is not None:
        if existing["username"] != resolved_username or existing["disabled_at"]:
            conn.execute(
                """
                UPDATE users
                SET username = ?, updated_at = ?, disabled_at = ''
                WHERE id = ?
                """,
                (resolved_username, now, existing["id"]),
            )
            existing = conn.execute("SELECT * FROM users WHERE id = ?", (existing["id"],)).fetchone()
        return dict(existing)

    matching_username = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        (resolved_username,),
    ).fetchone()
    if matching_username is not None:
        conn.execute(
            """
            UPDATE users
            SET source = 'env', updated_at = ?, disabled_at = ''
            WHERE id = ?
            """,
            (now, matching_username["id"]),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (matching_username["id"],)).fetchone()
        return dict(row)

    user_id = _stable_operator_user_id(resolved_username)
    conn.execute(
        """
        INSERT INTO users
        (id, username, display_name, source, created_at, updated_at, disabled_at)
        VALUES (?, ?, '', 'env', ?, ?, '')
        """,
        (user_id, resolved_username, now, now),
    )
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row)



def _seed_operator_user_from_env(conn: sqlite3.Connection) -> dict[str, Any]:
    return _seed_operator_user(conn, os.getenv("MOBILE_API_ADMIN_USERNAME", "admin"))



def get_or_seed_operator_user(db_path: Path, username: str | None = None) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        user = _seed_operator_user(conn, username)
        conn.commit()
        return user



def get_operator_user_id(db_path: Path, username: str | None = None) -> str:
    return str(get_or_seed_operator_user(db_path, username)["id"])



def find_user_by_username(db_path: Path, username: str) -> dict[str, Any] | None:
    resolved_username = username.strip()
    if not resolved_username:
        return None
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (resolved_username,),
        ).fetchone()
    return dict(row) if row else None



def _resolve_owner_user_id_for_write(db_path: Path, owner_user_id: str = "") -> str:
    resolved = str(owner_user_id or "").strip()
    if resolved:
        return resolved
    return get_operator_user_id(db_path)

