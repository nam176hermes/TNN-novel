from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.database.connection import get_connection
from app.mobile_api.config import MobileAPISettings


def _settings(*, batch_size: int = 2, interval_seconds: int = 21_600) -> MobileAPISettings:
    return MobileAPISettings(
        auth_session_retention_days=30,
        auth_session_retention_max_rows=5_000,
        auth_login_failure_retention_days=30,
        auth_login_failure_retention_max_rows=5_000,
        operational_event_retention_days=90,
        operational_event_retention_max_rows=50_000,
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
    service = retention_module.RetentionService(
        temp_db_path,
        settings=_settings(),
        yield_control=yield_control,
    )

    summary = await service.run_once()

    assert repository_calls == [
        ("auth", 2),
        ("auth", 2),
        ("operational_events", 2),
        ("operational_events", 2),
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
        "last_run": None,
    }
    assert str(temp_db_path) not in repr(status)


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
