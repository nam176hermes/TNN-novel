from __future__ import annotations

import asyncio
import threading

import pytest

from app.utils import asyncio_bridge
from app.utils.asyncio_bridge import run_coro_sync


async def _value(value: str) -> str:
    await asyncio.sleep(0)
    return value


def test_run_coro_sync_succeeds_from_plain_sync_context() -> None:
    assert run_coro_sync(_value("ok")) == "ok"


@pytest.mark.asyncio
async def test_run_coro_sync_succeeds_from_running_event_loop() -> None:
    loop_thread = threading.get_ident()

    async def current_thread_id() -> int:
        await asyncio.sleep(0)
        return threading.get_ident()

    result = run_coro_sync(current_thread_id())

    assert result != loop_thread


def test_run_coro_sync_propagates_coroutine_exceptions() -> None:
    async def explode() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_coro_sync(explode())


@pytest.mark.asyncio
async def test_run_coro_sync_does_not_call_asyncio_run_on_active_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    active_thread = threading.get_ident()
    original_asyncio_run = asyncio_bridge.asyncio.run
    calls: list[int] = []

    def guarded_run(coro):  # type: ignore[no-untyped-def]
        calls.append(threading.get_ident())
        if threading.get_ident() == active_thread:
            raise AssertionError("asyncio.run called from active event-loop thread")
        return original_asyncio_run(coro)

    monkeypatch.setattr(asyncio_bridge.asyncio, "run", guarded_run)

    assert run_coro_sync(_value("threaded")) == "threaded"
    assert calls
    assert active_thread not in calls
