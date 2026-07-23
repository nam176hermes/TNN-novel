from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
import threading
from typing import Any

import pytest

from app.database.connection import get_connection
from app.mobile_api.config import MobileAPISettings


def _settings(
    *,
    batch_size: int = 2,
    interval_seconds: int = 21_600,
    operational_max_rows: int = 50_000,
) -> MobileAPISettings:
    return MobileAPISettings(
        auth_session_retention_days=30,
        auth_session_retention_max_rows=5_000,
        auth_login_failure_retention_days=30,
        auth_login_failure_retention_max_rows=5_000,
        operational_event_retention_days=90,
        operational_event_retention_max_rows=operational_max_rows,
        operational_retention_batch_size=batch_size,
        operational_retention_interval_seconds=interval_seconds,
    )


@pytest.mark.asyncio
async def test_run_once_drains_multiple_bounded_batches_and_yields_between_them(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    auth_batches = iter(
        [
            {"auth_sessions": 2, "auth_login_failures": 0},
            {"auth_sessions": 0, "auth_login_failures": 1},
        ]
    )
    event_batches = iter([2, 1])
    repository_calls: list[tuple[str, int]] = []
    yields_after_call: list[int] = []
    recorded_events: list[dict[str, Any]] = []

    def prune_auth(*args: Any, **kwargs: Any) -> dict[str, int]:
        repository_calls.append(("auth", kwargs["batch_size"]))
        return next(auth_batches)

    def prune_events(*args: Any, **kwargs: Any) -> int:
        repository_calls.append(("operational_events", kwargs["batch_size"]))
        return next(event_batches)

    def record_event(*args: Any, **kwargs: Any) -> int:
        recorded_events.append(kwargs)
        return 1

    async def yield_control() -> None:
        yields_after_call.append(len(repository_calls))
        await asyncio.sleep(0)

    monkeypatch.setattr(retention_module, "prune_auth_records", prune_auth)
    monkeypatch.setattr(retention_module, "prune_operational_events", prune_events)
    monkeypatch.setattr(retention_module, "record_operational_event", record_event)
    monkeypatch.setattr(
        retention_module,
        "_count_retention_rows",
        lambda db_path: {
            "auth_sessions": 3,
            "auth_login_failures": 0,
            "operational_events": 3,
        },
    )
    service = retention_module.RetentionService(
        temp_db_path,
        settings=_settings(),
        yield_control=yield_control,
    )

    summary = await service.run_once()

    assert repository_calls == [
        ("auth", 2),
        ("auth", 1),
        ("operational_events", 2),
        ("operational_events", 1),
    ]
    assert yields_after_call == [1, 2, 3]
    assert summary.result == "completed"
    assert summary.deleted_counts == {
        "auth_sessions": 2,
        "auth_login_failures": 1,
        "operational_events": 3,
    }
    assert summary.last_run_at.endswith("+00:00")
    assert len(recorded_events) == 1
    event = recorded_events[0]
    assert event["event_type"] == "operational_retention"
    assert event["severity"] == "info"
    assert event["source"] == "retention"
    assert event["details"] == summary.deleted_counts
    assert all(isinstance(value, int) for value in event["details"].values())
    assert not any(key in event for key in ("path", "sql", "rows", "exception"))


@pytest.mark.asyncio
async def test_run_once_uses_initial_row_budget_under_sustained_full_batches(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    calls: list[tuple[str, int]] = []
    yields: list[int] = []

    monkeypatch.setattr(
        retention_module,
        "_count_retention_rows",
        lambda db_path: {
            "auth_sessions": 5,
            "auth_login_failures": 0,
            "operational_events": 4,
        },
    )

    def always_full_auth(*args: Any, **kwargs: Any) -> dict[str, int]:
        calls.append(("auth", kwargs["batch_size"]))
        return {"auth_sessions": kwargs["batch_size"], "auth_login_failures": 0}

    def always_full_events(*args: Any, **kwargs: Any) -> int:
        calls.append(("operational_events", kwargs["batch_size"]))
        return kwargs["batch_size"]

    async def yield_control() -> None:
        yields.append(len(calls))
        await asyncio.sleep(0)

    monkeypatch.setattr(retention_module, "prune_auth_records", always_full_auth)
    monkeypatch.setattr(retention_module, "prune_operational_events", always_full_events)
    monkeypatch.setattr(retention_module, "record_operational_event", lambda *args, **kwargs: 1)
    service = retention_module.RetentionService(
        temp_db_path,
        settings=_settings(),
        yield_control=yield_control,
    )

    summary = await asyncio.wait_for(service.run_once(), timeout=1)

    assert calls == [
        ("auth", 2),
        ("auth", 2),
        ("auth", 1),
        ("operational_events", 2),
        ("operational_events", 2),
    ]
    assert yields == [1, 2, 3, 4]
    assert summary.deleted_counts == {
        "auth_sessions": 5,
        "auth_login_failures": 0,
        "operational_events": 4,
    }


@pytest.mark.asyncio
async def test_run_once_does_not_record_an_event_when_nothing_was_deleted(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    recorded_events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        retention_module,
        "prune_auth_records",
        lambda *args, **kwargs: {"auth_sessions": 0, "auth_login_failures": 0},
    )
    monkeypatch.setattr(retention_module, "prune_operational_events", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        retention_module,
        "record_operational_event",
        lambda *args, **kwargs: recorded_events.append(kwargs),
    )
    service = retention_module.RetentionService(temp_db_path, settings=_settings())

    summary = await service.run_once()

    assert summary.result == "completed"
    assert sum(summary.deleted_counts.values()) == 0
    assert recorded_events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["database is locked", "database is busy"])
async def test_run_once_treats_sqlite_contention_as_a_safe_skipped_result(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    monkeypatch.setattr(
        retention_module,
        "prune_auth_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError(message)),
    )
    monkeypatch.setattr(
        retention_module,
        "_count_retention_rows",
        lambda db_path: {
            "auth_sessions": 1,
            "auth_login_failures": 0,
            "operational_events": 0,
        },
    )
    recorded_events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        retention_module,
        "record_operational_event",
        lambda *args, **kwargs: recorded_events.append(kwargs),
    )
    service = retention_module.RetentionService(temp_db_path, settings=_settings())

    summary = await service.run_once()

    assert summary.result == "skipped"
    assert sum(summary.deleted_counts.values()) == 0
    assert recorded_events == []
    assert message not in repr(summary)


def test_sqlite_contention_prefers_error_codes_with_narrow_message_fallback() -> None:
    from app.mobile_api.services.retention_service import _is_sqlite_contention

    coded_busy = sqlite3.OperationalError("opaque sqlite failure")
    coded_busy.sqlite_errorcode = sqlite3.SQLITE_BUSY

    assert _is_sqlite_contention(coded_busy) is True
    assert _is_sqlite_contention(sqlite3.OperationalError("database table is locked")) is True
    assert _is_sqlite_contention(sqlite3.OperationalError("busywork failed")) is False


@pytest.mark.asyncio
async def test_partial_deletion_busy_is_finalized_once_on_the_next_run(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    initial_counts = iter(
        [
            {"auth_sessions": 4, "auth_login_failures": 0, "operational_events": 0},
            {"auth_sessions": 0, "auth_login_failures": 0, "operational_events": 0},
            {"auth_sessions": 0, "auth_login_failures": 0, "operational_events": 0},
        ]
    )
    auth_calls = 0
    recorded: list[dict[str, Any]] = []

    monkeypatch.setattr(retention_module, "_count_retention_rows", lambda db_path: next(initial_counts))

    def prune_auth(*args: Any, **kwargs: Any) -> dict[str, int]:
        nonlocal auth_calls
        auth_calls += 1
        if auth_calls == 1:
            return {"auth_sessions": 2, "auth_login_failures": 0}
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(retention_module, "prune_auth_records", prune_auth)
    monkeypatch.setattr(retention_module, "record_operational_event", lambda *args, **kwargs: recorded.append(kwargs))
    service = retention_module.RetentionService(temp_db_path, settings=_settings())

    skipped = await service.run_once()
    recovered = await service.run_once()
    await service.run_once()

    assert skipped.result == "skipped"
    assert skipped.deleted_counts == {
        "auth_sessions": 2,
        "auth_login_failures": 0,
        "operational_events": 0,
    }
    assert recovered.result == "completed"
    assert len(recorded) == 1
    assert recorded[0]["details"] == skipped.deleted_counts


@pytest.mark.asyncio
async def test_busy_audit_insert_is_retried_once_on_the_next_run(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    initial_counts = iter(
        [
            {"auth_sessions": 2, "auth_login_failures": 0, "operational_events": 0},
            {"auth_sessions": 0, "auth_login_failures": 0, "operational_events": 0},
            {"auth_sessions": 0, "auth_login_failures": 0, "operational_events": 0},
        ]
    )
    successful_events: list[dict[str, Any]] = []
    event_attempts = 0

    monkeypatch.setattr(retention_module, "_count_retention_rows", lambda db_path: next(initial_counts))
    monkeypatch.setattr(
        retention_module,
        "prune_auth_records",
        lambda *args, **kwargs: {"auth_sessions": 2, "auth_login_failures": 0},
    )

    def record_event(*args: Any, **kwargs: Any) -> int:
        nonlocal event_attempts
        event_attempts += 1
        if event_attempts == 1:
            raise sqlite3.OperationalError("database is busy")
        successful_events.append(kwargs)
        return 1

    monkeypatch.setattr(retention_module, "record_operational_event", record_event)
    service = retention_module.RetentionService(temp_db_path, settings=_settings())

    skipped = await service.run_once()
    await service.run_once()
    await service.run_once()

    assert skipped.result == "skipped"
    assert event_attempts == 2
    assert len(successful_events) == 1
    assert successful_events[0]["details"] == skipped.deleted_counts


@pytest.mark.asyncio
async def test_retention_audit_respects_operational_event_cap_of_one(
    temp_db_path: Path,
) -> None:
    from app.mobile_api.services.retention_service import RetentionService

    with get_connection(temp_db_path) as conn:
        conn.executemany(
            """
            INSERT INTO operational_events (event_type, severity, source, message, created_at)
            VALUES (?, 'info', 'cap-test', 'safe', ?)
            """,
            [
                ("existing-1", "2026-07-13T00:00:00+00:00"),
                ("existing-2", "2026-07-13T00:00:01+00:00"),
                ("existing-3", "2026-07-13T00:00:02+00:00"),
            ],
        )
        conn.commit()
    service = RetentionService(
        temp_db_path,
        settings=_settings(operational_max_rows=1),
    )

    summary = await service.run_once()

    with get_connection(temp_db_path) as conn:
        rows = conn.execute(
            "SELECT event_type, details_json FROM operational_events ORDER BY id"
        ).fetchall()
    assert summary.deleted_counts["operational_events"] == 3
    assert len(rows) == 1
    assert rows[0]["event_type"] == "operational_retention"


@pytest.mark.asyncio
async def test_status_contains_only_table_counts_and_the_last_safe_summary(
    temp_db_path: Path,
) -> None:
    from app.mobile_api.services.retention_service import RetentionService

    with get_connection(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO auth_login_failures (rate_limit_key, username, client_host, failed_at)
            VALUES ('host:test', 'operator', '127.0.0.1', '2026-07-13T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO operational_events (event_type, severity, source, message)
            VALUES ('status-test', 'info', 'retention-test', 'safe')
            """
        )
        conn.commit()
    service = RetentionService(temp_db_path, settings=_settings())

    status = await service.get_status()

    assert status == {
        "table_counts": {
            "auth_sessions": 0,
            "auth_login_failures": 1,
            "operational_events": 1,
        },
        "auth_session_counts": {
            "total": 0,
            "active": 0,
            "expired": 0,
            "revoked": 0,
            "age_eligible": 0,
            "row_cap_eligible": 0,
            "would_remove": 0,
        },
        "last_run": None,
    }
    assert str(temp_db_path) not in repr(status)

    with pytest.raises(TypeError):
        await service.get_status(db_path=temp_db_path)


@pytest.mark.asyncio
async def test_status_count_can_run_while_a_retention_worker_is_active(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services import retention_service as retention_module

    worker_started = threading.Event()
    release_worker = threading.Event()
    count_calls = 0

    def count_rows(db_path: Path) -> dict[str, int]:
        nonlocal count_calls
        count_calls += 1
        if count_calls == 1:
            return {
                "auth_sessions": 1,
                "auth_login_failures": 0,
                "operational_events": 0,
            }
        return {
            "auth_sessions": 7,
            "auth_login_failures": 8,
            "operational_events": 9,
        }

    def blocking_prune(*args: Any, **kwargs: Any) -> dict[str, int]:
        worker_started.set()
        assert release_worker.wait(timeout=5)
        return {"auth_sessions": 0, "auth_login_failures": 0}

    monkeypatch.setattr(retention_module, "_count_retention_rows", count_rows)
    monkeypatch.setattr(retention_module, "prune_auth_records", blocking_prune)
    service = retention_module.RetentionService(temp_db_path, settings=_settings())
    run_task = asyncio.create_task(service.run_once())
    deadline = asyncio.get_running_loop().time() + 1
    while not worker_started.is_set() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert worker_started.is_set()

    status = await service.get_status()

    assert status["table_counts"] == {
        "auth_sessions": 7,
        "auth_login_failures": 8,
        "operational_events": 9,
    }
    release_worker.set()
    await asyncio.wait_for(run_task, timeout=1)


@pytest.mark.asyncio
async def test_retention_loop_runs_immediately_without_an_api_request() -> None:
    from app.mobile_api.services.retention_service import run_retention_loop

    stop_event = asyncio.Event()

    class FakeService:
        def __init__(self) -> None:
            self.runs = 0

        async def run_once(self) -> None:
            self.runs += 1
            stop_event.set()

    service = FakeService()

    await run_retention_loop(service, interval_seconds=21_600, stop_event=stop_event)

    assert service.runs == 1


@pytest.mark.asyncio
async def test_retention_loop_survives_a_maintenance_error_and_retries() -> None:
    from app.mobile_api.services.retention_service import run_retention_loop

    stop_event = asyncio.Event()

    class FlakyService:
        def __init__(self) -> None:
            self.runs = 0

        async def run_once(self) -> None:
            self.runs += 1
            if self.runs == 1:
                raise RuntimeError("private failure details")
            stop_event.set()

    service = FlakyService()

    await run_retention_loop(service, interval_seconds=0.001, stop_event=stop_event)

    assert service.runs == 2


@pytest.mark.asyncio
async def test_lifespan_owns_one_task_started_after_runtime_prep_and_awaits_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_module

    order: list[str] = []
    run_started = asyncio.Event()
    run_cancelled = asyncio.Event()

    class BlockingService:
        async def run_once(self) -> None:
            order.append("retention")
            run_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                run_cancelled.set()

    monkeypatch.setattr(main_module, "_prepare_runtime", lambda: order.append("prepare"))
    application = main_module.create_app(retention_service=BlockingService())

    assert order == ["prepare"]
    async with application.router.lifespan_context(application):
        await asyncio.wait_for(run_started.wait(), timeout=1)
        task = application.state.retention_task
        assert task is not None
        assert not task.done()
        assert order == ["prepare", "retention"]

    assert application.state.retention_task is None
    assert run_cancelled.is_set()
    assert task.done()


@pytest.mark.asyncio
async def test_lifespan_drains_active_sync_worker_before_clearing_task_state(
    temp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_module
    from app.mobile_api.services import retention_service as retention_module

    worker_started = threading.Event()
    release_worker = threading.Event()
    prune_calls = 0

    monkeypatch.setattr(main_module, "_prepare_runtime", lambda: None)
    monkeypatch.setattr(
        retention_module,
        "_count_retention_rows",
        lambda db_path: {
            "auth_sessions": 1,
            "auth_login_failures": 0,
            "operational_events": 0,
        },
    )

    def blocking_prune(*args: Any, **kwargs: Any) -> dict[str, int]:
        nonlocal prune_calls
        prune_calls += 1
        worker_started.set()
        assert release_worker.wait(timeout=5)
        return {"auth_sessions": 1, "auth_login_failures": 0}

    monkeypatch.setattr(retention_module, "prune_auth_records", blocking_prune)
    service = retention_module.RetentionService(temp_db_path, settings=_settings())
    application = main_module.create_app(retention_service=service)
    lifespan = application.router.lifespan_context(application)
    await lifespan.__aenter__()

    deadline = asyncio.get_running_loop().time() + 1
    while not worker_started.is_set() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert worker_started.is_set()
    retention_task = application.state.retention_task
    exit_task = asyncio.create_task(lifespan.__aexit__(None, None, None))
    await asyncio.sleep(0.05)

    assert not exit_task.done()
    assert application.state.retention_task is retention_task
    assert prune_calls == 1

    release_worker.set()
    await asyncio.wait_for(exit_task, timeout=1)

    assert application.state.retention_task is None
    assert retention_task.done()
    assert prune_calls == 1


@pytest.mark.asyncio
async def test_lifespan_rejects_duplicate_concurrent_maintenance_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api import main as main_module

    run_started = asyncio.Event()

    class BlockingService:
        async def run_once(self) -> None:
            run_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(main_module, "_prepare_runtime", lambda: None)
    application = main_module.create_app(retention_service=BlockingService())
    first = application.router.lifespan_context(application)
    await first.__aenter__()
    await asyncio.wait_for(run_started.wait(), timeout=1)
    second = application.router.lifespan_context(application)

    with pytest.raises(RuntimeError, match="already running"):
        await second.__aenter__()

    await first.__aexit__(None, None, None)
