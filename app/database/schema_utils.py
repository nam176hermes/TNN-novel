"""Shared idempotent SQLite schema inspection for initialization and repositories."""
from __future__ import annotations

import sqlite3

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None



def _column_default(conn: sqlite3.Connection, table_name: str, column_name: str) -> str | None:
    for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall():
        if row["name"] == column_name:
            return row["dflt_value"]
    return None



def _add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_sql: str) -> bool:
    column_name = column_sql.split()[0]
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
        return True
    return False

