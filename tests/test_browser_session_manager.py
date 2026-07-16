from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import stat
import tempfile
from typing import Any

import pytest

from app.utils import cookie_store


def test_cookie_store_uses_atomic_private_file(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        cookie_dir = Path(directory)
        monkeypatch.setattr(cookie_store, "_COOKIE_DIR", cookie_dir)
        url = "https://www.example.com/chapter/1"

        cookie_store.save_cookies(
            url,
            [{"name": "session", "value": "private", "domain": ".example.com", "path": "/"}],
        )

        cookie_path = cookie_dir / "www.example.com.json"
        assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600
        assert {path.name for path in cookie_dir.iterdir()} == {"www.example.com.json"}


def test_cookie_store_rotates_corrupt_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cookie_store, "_COOKIE_DIR", tmp_path)
    url = "https://www.example.com/chapter/1"
    cookie_path = tmp_path / "www.example.com.json"
    cookie_path.write_text("{not-json", encoding="utf-8")

    assert cookie_store.load_cookies(url) == []
    assert not cookie_path.exists()
    assert len(list(tmp_path.glob("www.example.com.json.corrupt-*"))) == 1


def test_cookie_store_tightens_legacy_file_permissions_on_load(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        cookie_dir = Path(directory)
        monkeypatch.setattr(cookie_store, "_COOKIE_DIR", cookie_dir)
        url = "https://www.example.com/chapter/1"
        cookie_path = cookie_dir / "www.example.com.json"
        cookie_path.write_text("[]", encoding="utf-8")
        cookie_path.chmod(0o644)

        assert cookie_store.load_cookies(url) == []
        assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600


def test_cookie_store_filters_expired_cookies_using_real_expiry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cookie_store, "_COOKIE_DIR", tmp_path)
    url = "https://www.example.com/chapter/1"
    cookie_path = tmp_path / "www.example.com.json"
    cookie_path.write_text(
        json.dumps(
            [
                {"name": "expired", "value": "old", "expires": 99},
                {"name": "valid", "value": "new", "expires": 101},
                {"name": "session", "value": "memory", "expires": -1},
            ]
        ),
        encoding="utf-8",
    )

    loaded = cookie_store.load_cookies(url, now=100)

    assert [cookie["name"] for cookie in loaded] == ["valid", "session"]


class FakeBrowser:
    def __init__(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected


class FakePage:
    def __init__(self, *, crash_once: bool = False, delay: float = 0.0) -> None:
        self.url = "about:blank"
        self.closed = False
        self.crash_once = crash_once
        self.delay = delay
        self.active = 0
        self.peak = 0
        self.handlers: dict[str, Any] = {}
        self.main_frame = object()

    def set_default_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    async def route(self, pattern: str, handler) -> None:
        self.route_handler = handler

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.crash_once:
                self.crash_once = False
                raise RuntimeError("Target page, context or browser has been closed")
            await asyncio.sleep(self.delay)
            self.url = url
        finally:
            self.active -= 1

    async def title(self) -> str:
        return "Novel"

    async def query_selector(self, selector: str):
        return None

    async def content(self) -> str:
        return "<html>chapter</html>"

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]
        self.browser = FakeBrowser()
        self.closed = False

    async def add_init_script(self, script: str) -> None:
        self.init_script = script

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    async def cookies(self) -> list[dict[str, Any]]:
        return []

    async def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self.added_cookies = cookies

    async def close(self) -> None:
        self.closed = True
        self.browser.connected = False
        for page in self.pages:
            await page.close()


class FakeChromium:
    def __init__(
        self,
        pages: list[FakePage],
        launched_contexts: list[FakeContext],
        launch_options: list[dict[str, Any]],
    ) -> None:
        self.pages = pages
        self.launched_contexts = launched_contexts
        self.launch_options = launch_options

    async def launch_persistent_context(self, profile_dir: str, **kwargs) -> FakeContext:
        self.launch_options.append(kwargs)
        context = FakeContext(self.pages.pop(0))
        self.launched_contexts.append(context)
        return context


class FakePlaywright:
    def __init__(
        self,
        pages: list[FakePage],
        launched_contexts: list[FakeContext],
        launch_options: list[dict[str, Any]],
    ) -> None:
        self.chromium = FakeChromium(pages, launched_contexts, launch_options)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def fake_playwright_factory(pages: list[FakePage]):
    launched_contexts: list[FakeContext] = []
    playwrights: list[FakePlaywright] = []
    launch_options: list[dict[str, Any]] = []

    async def factory() -> FakePlaywright:
        playwright = FakePlaywright(pages, launched_contexts, launch_options)
        playwrights.append(playwright)
        return playwright

    return factory, launched_contexts, playwrights, launch_options


def public_resolver(hostname: str, port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


@pytest.mark.asyncio
async def test_browser_session_serializes_fetches_with_per_session_lock(tmp_path) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    page = FakePage(delay=0.02)
    factory, contexts, _playwrights, _launch_options = fake_playwright_factory([page])
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    await asyncio.gather(
        manager.fetch("https://example.com/chapter/1"),
        manager.fetch("https://example.com/chapter/2"),
    )

    assert page.peak == 1
    assert len(contexts) == 1
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_restarts_after_browser_crash(tmp_path) -> None:
    from app.observability import InMemoryMetrics, Observability
    from app.utils.stealth_browser import BrowserSessionManager

    factory, contexts, playwrights, _launch_options = fake_playwright_factory(
        [FakePage(crash_once=True), FakePage()]
    )
    metrics = InMemoryMetrics()
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
        observability=Observability(metrics=metrics),
    )

    html = await manager.fetch("https://example.com/chapter/1")

    assert html == "<html>chapter</html>"
    assert len(contexts) == 2
    assert contexts[0].closed
    assert playwrights[0].stopped
    counters = {entry["name"]: entry["value"] for entry in metrics.snapshot()["counters"]}
    assert counters["browser_launches_total"] == 2
    assert counters["browser_restarts_total"] == 1
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_restarts_after_idle_ttl_and_request_ceiling(tmp_path) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    now = [0.0]
    factory, contexts, _playwrights, _launch_options = fake_playwright_factory(
        [FakePage(), FakePage(), FakePage()]
    )
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        idle_ttl_seconds=5,
        max_requests=1,
        resolver=public_resolver,
        clock=lambda: now[0],
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    await manager.fetch("https://example.com/chapter/1")
    await manager.fetch("https://example.com/chapter/2")
    now[0] = 10
    await manager.fetch("https://example.com/chapter/3")

    assert len(contexts) == 3
    assert contexts[0].closed and contexts[1].closed
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_cleanup_shutdown_closes_context_and_playwright(tmp_path) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    factory, contexts, playwrights, _launch_options = fake_playwright_factory([FakePage()])
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    await manager.fetch("https://example.com/chapter/1")
    await manager.close()
    await manager.close()

    assert contexts[0].closed
    assert playwrights[0].stopped


@pytest.mark.asyncio
async def test_browser_session_periodic_health_check_restarts_disconnected_browser(tmp_path) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    now = [0.0]
    factory, contexts, _playwrights, _launch_options = fake_playwright_factory(
        [FakePage(), FakePage()]
    )
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        health_check_interval_seconds=5,
        resolver=public_resolver,
        clock=lambda: now[0],
        sleep=lambda _seconds: asyncio.sleep(0),
    )
    await manager.fetch("https://example.com/chapter/1")
    contexts[0].browser.connected = False
    now[0] = 6

    await manager.fetch("https://example.com/chapter/2")

    assert len(contexts) == 2
    assert contexts[0].closed
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_disables_downloads_and_closes_popup(tmp_path) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    page = FakePage()
    factory, _contexts, _playwrights, launch_options = fake_playwright_factory([page])
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
    )
    await manager.fetch("https://example.com/chapter/1")
    popup = FakePage()

    page.handlers["popup"](popup)
    await asyncio.sleep(0)

    assert launch_options[0]["accept_downloads"] is False
    assert popup.closed
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_navigation_guard_blocks_private_top_level_target(tmp_path) -> None:
    from app.security.url_policy import UrlPolicyViolation
    from app.utils.stealth_browser import BrowserSessionManager

    class Request:
        url = "http://127.0.0.1/private"

        def __init__(self, frame) -> None:
            self.frame = frame

        def is_navigation_request(self) -> bool:
            return True

    class Route:
        def __init__(self) -> None:
            self.aborted = False
            self.continued = False

        async def abort(self, reason: str) -> None:
            self.aborted = True

        async def continue_(self) -> None:
            self.continued = True

    page = FakePage()
    factory, _contexts, _playwrights, _launch_options = fake_playwright_factory([page])
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
    )
    await manager.fetch("https://example.com/chapter/1")
    route = Route()

    await page.route_handler(route, Request(page.main_frame))

    assert route.aborted and not route.continued
    assert isinstance(manager._navigation_violation, UrlPolicyViolation)
    await manager.close()


def test_fetch_with_stealth_sync_delegates_to_session_runtime(monkeypatch) -> None:
    from app.utils import stealth_browser

    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(stealth_browser, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(
        stealth_browser._sync_browser_runtime,
        "fetch",
        lambda url, timeout: calls.append((url, timeout)) or "<html>ok</html>",
    )

    assert stealth_browser.fetch_with_stealth_sync("https://example.com/", timeout=123) == "<html>ok</html>"
    assert calls == [("https://example.com/", 123)]


def test_sync_browser_runtime_reuses_manager_and_cleans_up_worker_thread() -> None:
    from app.utils.stealth_browser import _SyncBrowserRuntime

    class Manager:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.closed = False

        async def fetch(self, url: str, timeout: int) -> str:
            self.calls.append(url)
            return f"<html>{timeout}</html>"

        async def close(self) -> None:
            self.closed = True

    managers: list[Manager] = []

    def manager_factory() -> Manager:
        manager = Manager()
        managers.append(manager)
        return manager

    runtime = _SyncBrowserRuntime(manager_factory=manager_factory)

    assert runtime.fetch("https://example.com/1", 100) == "<html>100</html>"
    assert runtime.fetch("https://example.com/2", 200) == "<html>200</html>"
    worker = runtime._thread
    runtime.close()
    runtime.close()

    assert len(managers) == 1
    assert managers[0].calls == ["https://example.com/1", "https://example.com/2"]
    assert managers[0].closed
    assert worker is not None and not worker.is_alive()


@pytest.mark.asyncio
async def test_cloudflare_reload_failure_log_does_not_expose_exception_payload(
    tmp_path,
    caplog,
) -> None:
    from app.utils.stealth_browser import BrowserSessionManager

    class ChallengePage(FakePage):
        async def title(self) -> str:
            return "Just a moment"

        async def wait_for_function(self, expression: str, *, timeout: int) -> None:
            raise RuntimeError("challenge remains")

        async def reload(self, **kwargs) -> None:
            raise RuntimeError("reload https://example.com/?token=must-not-log failed")

    factory, _contexts, _playwrights, _launch_options = fake_playwright_factory(
        [ChallengePage()]
    )
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=public_resolver,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    with caplog.at_level(logging.WARNING):
        await manager.fetch("https://example.com/chapter/1")

    assert "must-not-log" not in caplog.text
    assert "trying reload" in caplog.text
    await manager.close()


@pytest.mark.asyncio
async def test_browser_session_resolves_and_blocks_private_target_before_launch(tmp_path) -> None:
    from app.security.url_policy import UrlPolicyViolation
    from app.utils.stealth_browser import BrowserSessionManager

    factory, contexts, _playwrights, _launch_options = fake_playwright_factory([FakePage()])
    manager = BrowserSessionManager(
        playwright_factory=factory,
        profile_dir=tmp_path / "profile",
        resolver=lambda _hostname, _port: ("127.0.0.1",),
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    with pytest.raises(UrlPolicyViolation, match="Private or reserved"):
        await manager.fetch("https://public.example/chapter/1")

    assert contexts == []


@pytest.mark.asyncio
async def test_application_lifespan_closes_browser_session_runtime(monkeypatch) -> None:
    from app.mobile_api import main as main_module

    started = asyncio.Event()
    closed = asyncio.Event()

    class BlockingRetentionService:
        async def run_once(self) -> None:
            started.set()
            await asyncio.Event().wait()

    async def close_browser() -> None:
        closed.set()

    monkeypatch.setattr(main_module, "_prepare_runtime", lambda: None)
    monkeypatch.setattr(main_module, "close_stealth_browser", close_browser, raising=False)
    application = main_module.create_app(retention_service=BlockingRetentionService())

    async with application.router.lifespan_context(application):
        await asyncio.wait_for(started.wait(), timeout=1)

    assert closed.is_set()
