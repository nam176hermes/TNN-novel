from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from app.database.glossary_history import GLOSSARY_HISTORY_SCHEMA
from app.database.schema import SCHEMA


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _database_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _insert_term(
    conn: sqlite3.Connection,
    *,
    book_id: object,
    source: str,
    target: str,
    approved: object = 1,
    locked: object = 0,
    review_status: str = "APPROVED",
    mode: str = "translate",
) -> None:
    conn.execute(
        """
        INSERT INTO glossary_terms
            (book_id, source_term, target_term, approved, locked, review_status, mode)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (book_id, source, target, approved, locked, review_status, mode),
    )


def _baseline_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executescript(GLOSSARY_HISTORY_SCHEMA)
    _insert_term(conn, book_id=0, source="ordinary", target="confidential-result")
    _insert_term(
        conn,
        book_id=0,
        source="mismatched-state",
        target="confidential-result",
        review_status="NEEDS_REVIEW",
    )
    _insert_term(
        conn,
        book_id=0,
        source="invalid-tuple",
        target="confidential-result",
        approved=-1,
        locked=1,
        review_status="LOCKED",
    )
    conn.execute(
        """
        INSERT INTO glossary_terms
            (book_id, source_term, target_term, approved, locked, review_status, mode)
        VALUES (0, 'non-numeric-state', 'confidential-result', 'not-an-integer', 0, 'APPROVED', 'translate')
        """
    )
    _insert_term(conn, book_id=0, source="active-blank", target=" ", mode="")
    _insert_term(conn, book_id=5, source="\uff21\u3000Beta", target="one")
    _insert_term(conn, book_id=5, source="a beta", target="two")
    _insert_term(conn, book_id=0, source="shared", target="global")
    _insert_term(conn, book_id=5, source=" Shared ", target="book")
    conn.execute(
        """
        INSERT INTO glossary_history
            (book_id, source_term, target_term, action)
        VALUES (0, 'ordinary', 'confidential-result', 'add')
        """
    )
    conn.commit()
    conn.close()


def test_glossary_audit_is_read_only_and_redacts_private_values(tmp_path: Path) -> None:
    """Fails if audit writes data, returns findings as errors, or emits term values."""
    db_path = tmp_path / "baseline.db"
    _baseline_database(db_path)
    before = _database_digest(db_path)

    result = subprocess.run(
        [sys.executable, "scripts/audit_glossary_baseline.py", "--db", str(db_path)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert _database_digest(db_path) == before
    payload = json.loads(result.stdout)
    assert payload["counts"] == {
        "active_blank_targets": 1,
        "global_book_conflicts": {"groups": 1, "rows": 2},
        "history_coverage": {"terms_with_history": 1, "terms_without_history": 8},
        "legacy_blank_modes": 1,
        "normalized_same_book_collisions": {"groups": 1, "rows": 2},
        "state_mismatches": 3,
    }
    rendered = result.stdout + result.stderr
    assert "ordinary" not in rendered
    assert "mismatched-state" not in rendered
    assert "confidential-result" not in rendered
    assert str(db_path) not in rendered


def test_glossary_audit_returns_nonzero_only_for_runtime_failure(tmp_path: Path) -> None:
    """Fails if an unreadable database is reported as a successful audit."""
    missing_db = tmp_path / "missing.db"

    result = subprocess.run(
        [sys.executable, "scripts/audit_glossary_baseline.py", "--db", str(missing_db)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr.strip() == '{"error": "audit_failed"}'
    assert str(missing_db) not in result.stderr


def test_glossary_audit_keeps_noncanonical_state_and_scope_values_invalid(tmp_path: Path) -> None:
    """Fails if SQLite values are coerced into canonical states or valid book scopes."""
    db_path = tmp_path / "malformed.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    _insert_term(
        conn,
        book_id=1,
        source="scope-collision",
        target="book-target",
    )
    _insert_term(
        conn,
        book_id=1.5,
        source="scope collision",
        target="fractional-scope-target",
    )
    _insert_term(conn, book_id=0, source="scope-global", target="global-target")
    _insert_term(
        conn,
        book_id=1.5,
        source="scope global",
        target="fractional-scope-target",
    )
    _insert_term(
        conn,
        book_id=0,
        source="lowercase-status",
        target="state-target",
        review_status="approved",
    )
    _insert_term(
        conn,
        book_id=0,
        source="fractional-approved",
        target="state-target",
        approved=1.5,
    )
    _insert_term(
        conn,
        book_id=0,
        source="fractional-locked",
        target="state-target",
        locked=0.5,
    )
    conn.commit()
    conn.close()

    result = subprocess.run(
        [sys.executable, "scripts/audit_glossary_baseline.py", "--db", str(db_path)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["counts"]["state_mismatches"] == 3
    assert payload["counts"]["normalized_same_book_collisions"] == {"groups": 0, "rows": 0}
    assert payload["counts"]["global_book_conflicts"] == {"groups": 0, "rows": 0}


def test_synthetic_ten_thousand_row_characterization_covers_boundaries(tmp_path: Path) -> None:
    """Fails if the synthetic fixture stops characterizing the first page or final row."""
    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_glossary_baseline.py",
            "--rows",
            "10000",
            "--work-dir",
            str(tmp_path / "fixtures"),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "characterization": {
            "list": {"first_page_rows": 50, "returned_rows": 10000},
            "prompt": {"selected_rows": 2},
            "qa": {"matched_rows": 2},
            "query": {"first_page_rows": 50, "last_row_found": True},
        },
        "fixture": {"rows": 10000, "synthetic": True},
    }
    assert "ms" not in result.stdout
    assert "synthetic-source-" not in result.stdout
