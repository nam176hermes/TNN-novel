from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database.connection import get_connection
from app.database.auth_repository import prune_auth_records
from app.database.operations_repository import RetentionPolicy, prune_operational_events


NOW = "2026-02-15T00:00:00+00:00"


def _policy(*, days: int = 30, rows: int = 100) -> RetentionPolicy:
    return RetentionPolicy(max_age_days=days, max_rows=rows)


def _insert_session(
    db_path: Path,
    *,
    session_id: str,
    created_at: str,
    expires_at: str,
    revoked_at: str = "",
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
            (
                session_id, username, refresh_token_hash, refresh_family_id,
                created_at, expires_at, revoked_at, last_seen_at
            )
            VALUES (?, 'operator', ?, 'family', ?, ?, ?, ?)
            """,
            (session_id, f"hash-{session_id}", created_at, expires_at, revoked_at, created_at),
        )
        conn.commit()


def _insert_failure(db_path: Path, *, username: str, failed_at: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_login_failures (rate_limit_key, username, client_host, failed_at)
            VALUES (?, ?, '127.0.0.1', ?)
            """,
            (f"host:{username}", username, failed_at),
        )
        conn.commit()


def _insert_event(db_path: Path, *, event_type: str, created_at: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO operational_events (event_type, severity, source, message, created_at)
            VALUES (?, 'info', 'retention-test', ?, ?)
            """,
            (event_type, event_type, created_at),
        )
        conn.commit()


def _values(db_path: Path, table: str, column: str) -> list[str]:
    with get_connection(db_path) as conn:
        rows = conn.execute(f"SELECT {column} FROM {table} ORDER BY {column}").fetchall()
    return [str(row[column]) for row in rows]


def test_age_pruning_supports_timestamp_forms_and_preserves_active_sessions(
    temp_db_path: Path,
) -> None:
    _insert_session(
        temp_db_path,
        session_id="active-iso-old-created",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-03-01T00:00:00+00:00",
    )
    _insert_session(
        temp_db_path,
        session_id="active-space-old-created",
        created_at="2026-01-01 00:00:00",
        expires_at="2026-03-01 00:00:00",
    )
    _insert_session(
        temp_db_path,
        session_id="expired-old-iso",
        created_at="2025-12-01T00:00:00+00:00",
        expires_at="2026-01-01T00:00:00+00:00",
    )
    _insert_session(
        temp_db_path,
        session_id="expired-recent-space",
        created_at="2026-01-01 00:00:00",
        expires_at="2026-02-01 00:00:00",
    )
    _insert_session(
        temp_db_path,
        session_id="revoked-old-space",
        created_at="2025-12-01 00:00:00",
        expires_at="2026-03-01 00:00:00",
        revoked_at="2026-01-01 00:00:00",
    )
    _insert_session(
        temp_db_path,
        session_id="revoked-recent-iso",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-03-01T00:00:00+00:00",
        revoked_at="2026-02-01T00:00:00+00:00",
    )
    _insert_failure(temp_db_path, username="old-iso", failed_at="2026-01-01T00:00:00+00:00")
    _insert_failure(temp_db_path, username="old-space", failed_at="2026-01-01 00:00:00")
    _insert_failure(temp_db_path, username="recent", failed_at="2026-02-01T00:00:00+00:00")

    deleted = prune_auth_records(
        temp_db_path,
        session_policy=_policy(),
        login_failure_policy=_policy(),
        batch_size=20,
        now=NOW,
    )

    assert deleted == {"auth_sessions": 2, "auth_login_failures": 2}
    assert _values(temp_db_path, "auth_sessions", "session_id") == [
        "active-iso-old-created",
        "active-space-old-created",
        "expired-recent-space",
        "revoked-recent-iso",
    ]
    assert _values(temp_db_path, "auth_login_failures", "username") == ["recent"]


def test_operational_event_age_pruning_supports_timestamp_forms(temp_db_path: Path) -> None:
    _insert_event(temp_db_path, event_type="old-iso", created_at="2026-01-01T00:00:00+00:00")
    _insert_event(temp_db_path, event_type="old-space", created_at="2026-01-01 00:00:00")
    _insert_event(temp_db_path, event_type="recent", created_at="2026-02-01T00:00:00+00:00")

    deleted = prune_operational_events(
        temp_db_path,
        policy=_policy(),
        batch_size=20,
        now=NOW,
    )

    assert deleted == 2
    assert _values(temp_db_path, "operational_events", "event_type") == ["recent"]


def test_auth_count_pruning_is_batched_and_counts_only_inactive_sessions(
    temp_db_path: Path,
) -> None:
    for index in range(5):
        day = index + 1
        _insert_session(
            temp_db_path,
            session_id=f"inactive-{day}",
            created_at="2026-01-01T00:00:00+00:00",
            expires_at=f"2026-02-{day:02d}T00:00:00+00:00",
        )
    for index in range(4):
        _insert_session(
            temp_db_path,
            session_id=f"active-{index}",
            created_at="2025-01-01 00:00:00",
            expires_at="2026-03-01 00:00:00",
        )
    for index in range(5):
        _insert_failure(
            temp_db_path,
            username=f"failure-{index + 1}",
            failed_at=f"2026-02-{index + 1:02d} 12:00:00",
        )

    results = [
        prune_auth_records(
            temp_db_path,
            session_policy=_policy(days=365, rows=2),
            login_failure_policy=_policy(days=365, rows=2),
            batch_size=2,
            now=NOW,
        )
        for _ in range(4)
    ]

    assert results == [
        {"auth_sessions": 2, "auth_login_failures": 0},
        {"auth_sessions": 1, "auth_login_failures": 1},
        {"auth_sessions": 0, "auth_login_failures": 2},
        {"auth_sessions": 0, "auth_login_failures": 0},
    ]
    assert _values(temp_db_path, "auth_sessions", "session_id") == [
        "active-0",
        "active-1",
        "active-2",
        "active-3",
        "inactive-4",
        "inactive-5",
    ]
    assert _values(temp_db_path, "auth_login_failures", "username") == [
        "failure-4",
        "failure-5",
    ]


def test_operational_event_count_pruning_keeps_newest_cap_in_two_row_batches(
    temp_db_path: Path,
) -> None:
    for index in range(5):
        _insert_event(
            temp_db_path,
            event_type=f"event-{index + 1}",
            created_at=f"2026-02-{index + 1:02d}T00:00:00+00:00",
        )

    results = [
        prune_operational_events(
            temp_db_path,
            policy=_policy(days=365, rows=2),
            batch_size=2,
            now=NOW,
        )
        for _ in range(3)
    ]

    assert results == [2, 1, 0]
    assert _values(temp_db_path, "operational_events", "event_type") == [
        "event-4",
        "event-5",
    ]


def test_auth_age_pruning_precedes_count_overflow_with_one_shared_batch(
    temp_db_path: Path,
) -> None:
    for index in range(3):
        _insert_session(
            temp_db_path,
            session_id=f"recent-inactive-{index}",
            created_at="2026-02-01T00:00:00+00:00",
            expires_at=f"2026-02-{index + 10:02d}T00:00:00+00:00",
        )
    _insert_failure(temp_db_path, username="old", failed_at="2026-01-01 00:00:00")

    deleted = prune_auth_records(
        temp_db_path,
        session_policy=_policy(rows=2),
        login_failure_policy=_policy(rows=100),
        batch_size=1,
        now=NOW,
    )

    assert deleted == {"auth_sessions": 0, "auth_login_failures": 1}
    assert len(_values(temp_db_path, "auth_sessions", "session_id")) == 3


def test_auth_pruning_rolls_back_entire_batch_when_second_delete_fails(
    temp_db_path: Path,
) -> None:
    _insert_session(
        temp_db_path,
        session_id="old-revoked",
        created_at="2025-12-01T00:00:00+00:00",
        expires_at="2026-03-01T00:00:00+00:00",
        revoked_at="2026-01-01T00:00:00+00:00",
    )
    _insert_failure(temp_db_path, username="old", failed_at="2026-01-01 00:00:00")
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_login_failure_delete
            BEFORE DELETE ON auth_login_failures
            BEGIN
                SELECT RAISE(ABORT, 'injected delete failure');
            END
            """
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected delete failure"):
        prune_auth_records(
            temp_db_path,
            session_policy=_policy(),
            login_failure_policy=_policy(),
            batch_size=2,
            now=NOW,
        )

    assert _values(temp_db_path, "auth_sessions", "session_id") == ["old-revoked"]
    assert _values(temp_db_path, "auth_login_failures", "username") == ["old"]


def test_operational_pruning_rolls_back_age_delete_when_count_delete_fails(
    temp_db_path: Path,
) -> None:
    _insert_event(temp_db_path, event_type="age-old", created_at="2026-01-01 00:00:00")
    _insert_event(
        temp_db_path,
        event_type="count-failure",
        created_at="2026-02-01T00:00:00+00:00",
    )
    _insert_event(temp_db_path, event_type="newest", created_at="2026-02-02 00:00:00")
    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_count_event_delete
            BEFORE DELETE ON operational_events
            WHEN OLD.event_type = 'count-failure'
            BEGIN
                SELECT RAISE(ABORT, 'injected count delete failure');
            END
            """
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected count delete failure"):
        prune_operational_events(
            temp_db_path,
            policy=_policy(rows=1),
            batch_size=2,
            now=NOW,
        )

    assert _values(temp_db_path, "operational_events", "event_type") == [
        "age-old",
        "count-failure",
        "newest",
    ]
