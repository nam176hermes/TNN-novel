"""
Glossary history — atomic writes + audit trail for glossary changes.

Ported from QuickTranslator's history logging pattern:
- Every glossary edit logged as TSV with timestamp, action, user
- Atomic file writes using temp + rename
- DB-level history table for term-level tracking
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


GLOSSARY_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER DEFAULT 0,
    source_term TEXT NOT NULL,
    target_term TEXT DEFAULT '',
    action TEXT NOT NULL,              -- 'add', 'update', 'approve', 'reject', 'delete', 'mode_change'
    old_target TEXT DEFAULT '',
    old_mode TEXT DEFAULT '',
    new_mode TEXT DEFAULT '',
    user TEXT DEFAULT '',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_glossary_history_source ON glossary_history(source_term);
CREATE INDEX IF NOT EXISTS idx_glossary_history_book ON glossary_history(book_id);
CREATE INDEX IF NOT EXISTS idx_glossary_history_ts ON glossary_history(timestamp);
"""


def ensure_history_table(conn: sqlite3.Connection) -> None:
    """Create glossary_history table if not exists."""
    conn.executescript(GLOSSARY_HISTORY_SCHEMA)
    conn.commit()


def log_glossary_change(
    conn: sqlite3.Connection,
    book_id: int,
    source_term: str,
    action: str,
    target_term: str = "",
    old_target: str = "",
    old_mode: str = "",
    new_mode: str = "",
) -> None:
    """Log a glossary change to the history table."""
    ensure_history_table(conn)
    user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
    conn.execute(
        """
        INSERT INTO glossary_history
            (book_id, source_term, target_term, action, old_target, old_mode, new_mode, user)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (book_id, source_term, target_term, action, old_target, old_mode, new_mode, user),
    )


def get_glossary_history(
    conn: sqlite3.Connection,
    source_term: Optional[str] = None,
    book_id: Optional[int] = None,
    limit: int = 50,
) -> List[dict]:
    """Get glossary change history, optionally filtered by term or book."""
    ensure_history_table(conn)
    conditions: List[str] = []
    params: List = []

    if source_term:
        conditions.append("source_term = ?")
        params.append(source_term)
    if book_id is not None:
        conditions.append("book_id = ?")
        params.append(book_id)

    where = " AND ".join(conditions) if conditions else "1"
    rows = conn.execute(
        f"SELECT * FROM glossary_history WHERE {where} ORDER BY timestamp DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_glossary_history_stats(conn: sqlite3.Connection) -> dict:
    """Return summary stats for glossary history."""
    ensure_history_table(conn)
    total = conn.execute("SELECT COUNT(*) FROM glossary_history").fetchone()[0]
    by_action = {}
    for row in conn.execute(
        "SELECT action, COUNT(*) FROM glossary_history GROUP BY action"
    ).fetchall():
        by_action[row[0]] = row[1]
    last_edit = conn.execute(
        "SELECT timestamp, source_term, action FROM glossary_history ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return {
        "total_edits": total,
        "by_action": by_action,
        "last_edit": dict(last_edit) if last_edit else None,
    }


def atomic_write(path: Path, content: str) -> None:
    """Write file atomically: temp file + os.replace (atomic on POSIX).

    Ported from QuickTranslator's atomic save with backup pattern.
    """
    temp_path = path.with_suffix(f".tmp.{os.getpid()}")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def atomic_write_with_backup(path: Path, content: str) -> Optional[Path]:
    """Write file atomically, creating a timestamped backup of previous content.

    Returns path to backup file, or None if no previous file existed.
    Ported from QuickTranslator's backup-first write pattern.
    """
    backup_path: Optional[Path] = None
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_suffix(f".{ts}.bak")
        with open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(path.read_text(encoding="utf-8"))

    atomic_write(path, content)
    return backup_path


def json_glossary_to_csv(
    glossary_dict: Dict[str, str],
    book_id: int = 0,
    category: str = "term",
) -> str:
    """Convert a simple glossary dict to CSV format for export.

    Format: book_id|source_term|target_term|category|timestamp
    """
    now = datetime.now().isoformat()
    lines = ["source_term|target_term|book_id|category|timestamp"]
    for src, tgt in sorted(glossary_dict.items(), key=len, reverse=True):
        lines.append(f"{src}|{tgt}|{book_id}|{category}|{now}")
    return "\n".join(lines)
