from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import auth_repository
from app.database import db


def _future_timestamp(*, hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _create_session(
    db_path: Path,
    *,
    session_id: str = "session-1",
    username: str = "operator",
    refresh_token_hash: str = "refresh-1",
) -> None:
    auth_repository.create_auth_session(
        db_path,
        session_id=session_id,
        username=username,
        user_id="user-1",
        refresh_token_hash=refresh_token_hash,
        refresh_family_id="family-1",
        expires_at=_future_timestamp(),
        client_host="127.0.0.1",
        user_agent="pytest",
        request_id="request-1",
    )


def test_db_auth_exports_are_repository_function_objects() -> None:
    assert db.create_auth_session is auth_repository.create_auth_session
    assert db.get_auth_session is auth_repository.get_auth_session
    assert db.touch_auth_session is auth_repository.touch_auth_session
    assert db.auth_session_is_active is auth_repository.auth_session_is_active
    assert db.revoke_auth_session is auth_repository.revoke_auth_session
    assert (
        db.revoke_auth_sessions_for_username
        is auth_repository.revoke_auth_sessions_for_username
    )
    assert db.rotate_auth_session_refresh is auth_repository.rotate_auth_session_refresh
    assert db.record_auth_login_failure is auth_repository.record_auth_login_failure
    assert db.count_auth_login_failures is auth_repository.count_auth_login_failures
    assert db.clear_auth_login_failures is auth_repository.clear_auth_login_failures


def test_create_get_touch_and_revoke_auth_session(temp_db_path: Path) -> None:
    _create_session(temp_db_path)

    created = auth_repository.get_auth_session(temp_db_path, "session-1")
    assert created is not None
    assert created["session_id"] == "session-1"
    assert created["username"] == "operator"
    assert created["user_id"] == "user-1"
    assert created["refresh_token_hash"] == "refresh-1"
    assert created["refresh_family_id"] == "family-1"
    assert created["revoked_at"] == ""
    assert created["last_seen_at"]
    assert created["client_host"] == "127.0.0.1"
    assert created["user_agent"] == "pytest"
    assert created["request_id"] == "request-1"
    assert auth_repository.auth_session_is_active(created, username="operator") is True
    assert auth_repository.auth_session_is_active(created, username="someone-else") is False

    auth_repository.touch_auth_session(temp_db_path, "session-1")
    touched = auth_repository.get_auth_session(temp_db_path, "session-1")
    assert touched is not None
    assert touched["last_seen_at"] >= created["last_seen_at"]

    assert auth_repository.revoke_auth_session(temp_db_path, "session-1") == 1
    assert auth_repository.revoke_auth_session(temp_db_path, "session-1") == 0
    revoked = auth_repository.get_auth_session(temp_db_path, "session-1")
    assert revoked is not None
    assert revoked["revoked_at"]
    assert auth_repository.auth_session_is_active(revoked) is False


def test_revoke_auth_sessions_for_username_only_revokes_matching_sessions(
    temp_db_path: Path,
) -> None:
    _create_session(temp_db_path, session_id="operator-1")
    _create_session(temp_db_path, session_id="operator-2")
    _create_session(temp_db_path, session_id="reader-1", username="reader")

    assert auth_repository.revoke_auth_sessions_for_username(temp_db_path, "operator") == 2
    assert auth_repository.auth_session_is_active(
        auth_repository.get_auth_session(temp_db_path, "operator-1")
    ) is False
    assert auth_repository.auth_session_is_active(
        auth_repository.get_auth_session(temp_db_path, "reader-1")
    ) is True


def test_rotate_auth_session_refresh_and_detect_reuse(temp_db_path: Path) -> None:
    _create_session(temp_db_path)
    next_expiry = _future_timestamp(hours=2)

    status, rotated = auth_repository.rotate_auth_session_refresh(
        temp_db_path,
        session_id="session-1",
        current_refresh_token_hash="refresh-1",
        next_refresh_token_hash="refresh-2",
        next_expires_at=next_expiry,
    )

    assert status == "rotated"
    assert rotated is not None
    assert rotated["refresh_token_hash"] == "refresh-2"
    assert rotated["expires_at"] == next_expiry

    status, replayed = auth_repository.rotate_auth_session_refresh(
        temp_db_path,
        session_id="session-1",
        current_refresh_token_hash="refresh-1",
        next_refresh_token_hash="refresh-3",
        next_expires_at=_future_timestamp(hours=3),
    )

    assert status == "reuse_detected"
    assert replayed is not None
    assert replayed["revoked_at"]
    assert replayed["reuse_detected_at"] == replayed["revoked_at"]


def test_record_count_and_clear_auth_login_failures(temp_db_path: Path) -> None:
    auth_repository.record_auth_login_failure(
        temp_db_path,
        rate_limit_key="host:operator",
        username="operator",
        client_host="127.0.0.1",
        failed_at="2026-01-01T00:00:01+00:00",
    )
    auth_repository.record_auth_login_failure(
        temp_db_path,
        rate_limit_key="host:operator",
        username="operator",
        failed_at="2026-01-01T00:00:02+00:00",
    )
    auth_repository.record_auth_login_failure(
        temp_db_path,
        rate_limit_key="other-key",
        username="operator",
        failed_at="2026-01-01T00:00:03+00:00",
    )

    assert auth_repository.count_auth_login_failures(
        temp_db_path,
        rate_limit_key="host:operator",
        since="2026-01-01T00:00:01+00:00",
    ) == 1

    auth_repository.clear_auth_login_failures(
        temp_db_path,
        rate_limit_key="host:operator",
    )

    assert auth_repository.count_auth_login_failures(
        temp_db_path,
        rate_limit_key="host:operator",
        since="2025-01-01T00:00:00+00:00",
    ) == 0
    assert auth_repository.count_auth_login_failures(
        temp_db_path,
        rate_limit_key="other-key",
        since="2025-01-01T00:00:00+00:00",
    ) == 1
