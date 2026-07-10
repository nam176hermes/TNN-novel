#!/usr/bin/env python3
"""Browser smoke test for the reader page.

The script starts the local API/Vite app when needed, seeds one translated
chapter through the API, drives the reader UI with Playwright, and stores
mobile/desktop screenshots under output/playwright/.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if (
    VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
    and not os.getenv("SMOKE_READER_NO_VENV_REEXEC")
):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

from dotenv import load_dotenv

DEFAULT_API_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_WEB_URL = DEFAULT_API_BASE_URL
DEFAULT_TIMEOUT_MS = 15_000
USER_AGENT = "novel-pipeline-reader-smoke/1.0"

SOURCE_TEXT = """少年站在山门前，雨声穿过松林。

长老缓缓开口，让他记住此夜。

他低声应诺，把旧剑抱在怀中。

远处钟声一响，众弟子齐齐回首。
"""

TRANSLATION_TEXT = """Thiếu niên đứng trước sơn môn, tiếng mưa xuyên qua rừng tùng.

Trưởng lão chậm rãi mở lời, bảo hắn phải ghi nhớ đêm này.

Hắn khẽ vâng, ôm thanh kiếm cũ vào lòng.

Xa xa chuông ngân một tiếng, chúng đệ tử đồng loạt ngoảnh đầu.

Một luồng linh khí lạnh thấm qua thềm đá, khiến ngọn đèn trước điện khẽ lay động.

Đây là đoạn dùng để kiểm tra chế độ lật trang của reader smoke.
"""

READER_API_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("reader/progress", re.compile(r"^/api/books/\d+/reader/progress$")),
    ("reader/state", re.compile(r"^/api/books/\d+/reader/state$")),
    ("reader/xray", re.compile(r"^/api/books/\d+/reader/xray$")),
    ("reader/explain", re.compile(r"^/api/books/\d+/chapters/\d+/reader/explain$")),
    ("chapter_annotations", re.compile(r"^/api/books/\d+/chapters/\d+/annotations$")),
    ("annotations", re.compile(r"^/api/books/\d+/annotations(?:/\d+)?$")),
    ("search", re.compile(r"^/api/books/\d+/search$")),
)


@dataclass
class SmokeBook:
    book_id: int
    chapter_id: int
    note_text: str
    title: str


def classify_reader_api_url(url: str) -> str | None:
    path = urlparse(url).path
    for kind, pattern in READER_API_PATTERNS:
        if pattern.match(path):
            return kind
    return None


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 10.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def request_text(url: str, *, timeout: float = 5.0) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc


def wait_for_api(api_base_url: str, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    ready_url = f"{api_base_url.rstrip('/')}/api/ready"
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = request_json("GET", ready_url, timeout=2.0)
            if payload.get("status") == "ok":
                return
            last_error = f"unexpected payload {payload}"
        except Exception as exc:  # noqa: BLE001 - keep polling with the last concrete error.
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"API did not become ready at {ready_url}: {last_error}")


def wait_for_web(web_url: str, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    index_url = web_url.rstrip("/") + "/"
    last_error = ""
    while time.monotonic() < deadline:
        try:
            html = request_text(index_url, timeout=2.0)
            lowered = html.lower()
            if "<html" in lowered or "<!doctype html" in lowered:
                return
            last_error = "response did not look like HTML"
        except Exception as exc:  # noqa: BLE001 - keep polling with the last concrete error.
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Web app did not become ready at {index_url}: {last_error}")


def ensure_local_app(api_base_url: str, web_url: str) -> None:
    try:
        wait_for_api(api_base_url, timeout_seconds=3)
        wait_for_web(web_url, timeout_seconds=3)
        return
    except Exception:
        if not env_bool("SMOKE_READER_START_SERVERS", True):
            raise

    subprocess.run([str(ROOT / "scripts" / "start-local.sh")], cwd=ROOT, check=True)
    wait_for_api(api_base_url)
    wait_for_web(web_url)


def login(api_base_url: str, username: str, password: str) -> str:
    payload = request_json(
        "POST",
        f"{api_base_url.rstrip('/')}/api/auth/login",
        payload={"username": username, "password": password},
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Login response did not include access_token")
    return token


def seed_translated_chapter(api_base_url: str, token: str) -> SmokeBook:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    title = f"Smoke Reader QA {stamp}"
    note_text = f"Smoke note {stamp}"
    imported = request_json(
        "POST",
        f"{api_base_url.rstrip('/')}/api/import/paste",
        token=token,
        payload={
            "title": title,
            "chapter_number": 1,
            "chapter_title": "Reader Smoke",
            "text": SOURCE_TEXT,
        },
    )
    book_id = int(imported["book_id"])
    chapter_id = int(imported["chapter_id"])
    title = str(imported.get("title") or title)
    request_json(
        "PATCH",
        f"{api_base_url.rstrip('/')}/api/books/{book_id}/chapters/{chapter_id}/translation",
        token=token,
        payload={"text": TRANSLATION_TEXT},
    )
    return SmokeBook(book_id=book_id, chapter_id=chapter_id, note_text=note_text, title=title)


def cleanup_smoke_book(api_base_url: str, token: str, smoke_book: SmokeBook | None) -> None:
    if not smoke_book or env_bool("SMOKE_READER_KEEP_DATA", False):
        return
    try:
        request_json("DELETE", f"{api_base_url.rstrip('/')}/api/books/{smoke_book.book_id}", token=token)
    except Exception as exc:  # noqa: BLE001 - cleanup should not hide the smoke result.
        print(f"WARN cleanup failed for smoke book {smoke_book.book_id}: {exc}", file=sys.stderr)


def run_browser_smoke(
    *,
    api_base_url: str,
    password: str,
    smoke_book: SmokeBook,
    token: str,
    username: str,
    web_url: str,
) -> tuple[Path, Path]:
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright Python is not installed. Run: .venv/bin/python -m pip install playwright && "
            ".venv/bin/python -m playwright install chromium"
        ) from exc

    artifact_dir = Path(os.getenv("SMOKE_READER_ARTIFACT_DIR", ROOT / "output" / "playwright"))
    if not artifact_dir.is_absolute():
        artifact_dir = ROOT / artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    mobile_screenshot = artifact_dir / "reader-smoke-mobile.png"
    desktop_screenshot = artifact_dir / "reader-smoke-desktop.png"
    timeout_ms = int(os.getenv("SMOKE_READER_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)))
    headless = env_bool("SMOKE_READER_HEADLESS", True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        reader_api_errors: list[str] = []
        reader_api_hits: set[str] = set()

        def record_reader_response(response: Any) -> None:
            kind = classify_reader_api_url(response.url)
            if not kind:
                return
            reader_api_hits.add(kind)
            if response.status >= 400:
                reader_api_errors.append(f"{response.request.method} {response.url} -> HTTP {response.status}")

        def record_reader_request_failed(request: Any) -> None:
            kind = classify_reader_api_url(request.url)
            if not kind:
                return
            reader_api_hits.add(kind)
            failure = request.failure or "unknown request failure"
            reader_api_errors.append(f"{request.method} {request.url} -> {failure}")

        def fail_on_reader_api_errors() -> None:
            if reader_api_errors:
                raise AssertionError("Reader API failure(s):\n" + "\n".join(f"- {item}" for item in reader_api_errors))

        def wait_for_reader_response(kind: str, action: Any) -> None:
            with page.expect_response(lambda response: classify_reader_api_url(response.url) == kind):
                action()
            fail_on_reader_api_errors()

        page.on("response", record_reader_response)
        page.on("requestfailed", record_reader_request_failed)

        page.goto(web_url.rstrip("/") + "/", wait_until="networkidle")
        login_form = page.get_by_label("Username")
        if login_form.count() > 0 and login_form.first.is_visible():
            login_form.first.fill(username)
            page.get_by_label("Password").fill(password)
            page.get_by_role("button", name="Login").click()
        else:
            page.evaluate(
                """(accessToken) => {
                    window.localStorage.setItem('novel-operator-token', accessToken);
                }""",
                token,
            )
            page.reload(wait_until="networkidle")
        expect(page.get_by_role("button", name="Thư viện")).to_be_visible()

        page.get_by_role("button", name="Thư viện").click()
        expect(page.get_by_role("heading", name="Thư viện đã dịch")).to_be_visible()
        page.get_by_role("button", name="Làm mới").click()
        page.get_by_label("Tìm sách").fill(smoke_book.title)
        open_book = page.get_by_label(f"Mở sách {smoke_book.title}").first
        expect(open_book).to_be_visible()
        open_book.click()

        reader = page.get_by_role("region", name="Trang đọc truyện")
        expect(reader).to_be_visible()
        article = page.get_by_role("article", name="Nội dung đọc tiếng Việt")
        expect(article).to_contain_text("Thiếu niên đứng trước sơn môn")
        fail_on_reader_api_errors()
        page.evaluate(
            """async ({ apiBaseUrl, bookId, chapterId }) => {
                const token = window.localStorage.getItem('novel-operator-token') || '';
                const response = await fetch(`${apiBaseUrl}/api/books/${bookId}/reader/progress`, {
                    method: 'PATCH',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        chapter_id: chapterId,
                        mode: 'scroll',
                        percent: 1,
                        paragraph_index: 0,
                        char_offset: 0,
                        page_index: 0
                    })
                });
                if (!response.ok) {
                    throw new Error(`reader progress smoke PATCH failed: ${response.status} ${await response.text()}`);
                }
            }""",
            {"apiBaseUrl": api_base_url.rstrip("/"), "bookId": smoke_book.book_id, "chapterId": smoke_book.chapter_id},
        )
        fail_on_reader_api_errors()

        page.get_by_role("button", name="Cài đặt chữ").click()
        settings = page.get_by_role("dialog", name="Cài đặt đọc")
        expect(settings).to_be_visible()
        settings.get_by_role("button", name="Trang").click()
        expect(article).to_have_attribute("data-reading-mode", "paginated")
        settings.get_by_role("button", name="Cuộn").click()
        expect(article).to_have_attribute("data-reading-mode", "scroll")
        settings.get_by_label("Instant mode").check()
        page.get_by_role("button", name="Đóng cài đặt đọc").click()

        bookmark = page.get_by_role("button", name="Đánh dấu trang")
        wait_for_reader_response("chapter_annotations", bookmark.click)
        expect(bookmark).to_have_attribute("aria-pressed", "true")

        wait_for_reader_response("chapter_annotations", page.get_by_role("button", name="Đánh dấu đoạn 1").click)
        expect(page.locator('.reader-paragraph-block[data-paragraph-index="0"]')).to_have_attribute(
            "data-highlighted",
            "true",
        )

        page.get_by_role("button", name="Ghi chú đoạn 2").click()
        note_dialog = page.get_by_role("dialog", name="Ghi chú đoạn đọc")
        expect(note_dialog).to_be_visible()
        note_dialog.get_by_label("Nội dung ghi chú").fill(smoke_book.note_text)
        wait_for_reader_response("chapter_annotations", note_dialog.get_by_role("button", name="Lưu ghi chú").click)
        expect(page.get_by_role("button", name="Mở ghi chú đoạn 2")).to_contain_text(smoke_book.note_text)
        updated_note_text = f"{smoke_book.note_text} updated"
        page.get_by_role("button", name="Mở ghi chú đoạn 2").click()
        note_dialog = page.get_by_role("dialog", name="Ghi chú đoạn đọc")
        expect(note_dialog).to_be_visible()
        note_dialog.get_by_label("Nội dung ghi chú").fill(updated_note_text)
        wait_for_reader_response("annotations", note_dialog.get_by_role("button", name="Lưu ghi chú").click)
        expect(page.get_by_role("button", name="Mở ghi chú đoạn 2")).to_contain_text(updated_note_text)

        page.get_by_role("button", name="Tìm kiếm").click()
        search_panel = page.get_by_role("dialog", name="Tìm trong truyện")
        expect(search_panel).to_be_visible()
        wait_for_reader_response("search", lambda: search_panel.get_by_label("Từ khóa").fill(updated_note_text))
        expect(search_panel).to_contain_text(updated_note_text)
        search_panel.get_by_role("button", name="Đóng tìm kiếm").click()

        reader.evaluate(
            """(element) => {
                element.scrollTop = Math.min(element.scrollHeight, element.clientHeight + 120);
                element.dispatchEvent(new Event('scroll', { bubbles: true }));
            }""",
        )
        page.wait_for_timeout(500)
        fail_on_reader_api_errors()

        page.get_by_role("button", name="Thêm tùy chọn").click()
        wait_for_reader_response("reader/xray", page.get_by_role("button", name="Mở X-Ray").click)
        xray_panel = page.get_by_role("dialog", name="X-Ray truyện")
        expect(xray_panel).to_be_visible()
        page.get_by_role("button", name="Đóng X-Ray").click()

        page.get_by_role("button", name="Thêm tùy chọn").click()
        page.get_by_role("button", name="Mở dấu đọc").click()
        marks_panel = page.get_by_role("dialog", name="Dấu đọc")
        expect(marks_panel).to_be_visible()
        expect(marks_panel).to_contain_text("Đánh dấu chương")
        marks_panel.get_by_role("button", name="Highlights").click()
        expect(marks_panel).to_contain_text("Thiếu niên đứng trước sơn môn")
        marks_panel.get_by_role("button", name="Notes").click()
        expect(marks_panel).to_contain_text(updated_note_text)
        page.get_by_role("button", name="Đóng dấu đọc").click()
        audio_panel = page.get_by_role("region", name="Audio và TTS chương")
        expect(audio_panel).to_be_visible()
        fail_on_reader_api_errors()

        required_reader_hits = {
            "reader/progress",
            "reader/state",
            "reader/xray",
            "annotations",
            "chapter_annotations",
            "search",
        }
        missing_reader_hits = sorted(required_reader_hits - reader_api_hits)
        if missing_reader_hits:
            raise AssertionError(
                "Reader browser flow did not hit expected API endpoint(s): " + ", ".join(missing_reader_hits)
            )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        expect(audio_panel).to_be_visible()
        mobile_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
        )
        if mobile_overflow:
            raise AssertionError("Reader mobile layout has horizontal overflow")
        page.screenshot(path=mobile_screenshot, full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.wait_for_timeout(250)
        page.screenshot(path=desktop_screenshot, full_page=True)

        context.close()
        browser.close()

    return mobile_screenshot, desktop_screenshot


def main() -> int:
    load_dotenv(ROOT / ".env")
    default_api_base_url = f"http://127.0.0.1:{os.getenv('MOBILE_API_PORT', '7860')}"
    api_base_url = os.getenv(
        "SMOKE_API_BASE_URL",
        os.getenv("API_BASE_URL", default_api_base_url or DEFAULT_API_BASE_URL),
    ).rstrip("/")
    web_url = os.getenv("SMOKE_WEB_URL", os.getenv("WEB_URL", api_base_url or DEFAULT_WEB_URL)).rstrip("/")
    username = os.getenv("MOBILE_API_ADMIN_USERNAME", "admin")
    password = os.getenv("MOBILE_API_ADMIN_PASSWORD", "change_me")

    smoke_book: SmokeBook | None = None
    token = ""
    try:
        ensure_local_app(api_base_url, web_url)
        token = login(api_base_url, username, password)
        smoke_book = seed_translated_chapter(api_base_url, token)
        mobile_screenshot, desktop_screenshot = run_browser_smoke(
            api_base_url=api_base_url,
            password=password,
            smoke_book=smoke_book,
            token=token,
            username=username,
            web_url=web_url,
        )
        print(f"OK reader browser smoke: {smoke_book.title}")
        print(f"OK mobile screenshot: {mobile_screenshot}")
        print(f"OK desktop screenshot: {desktop_screenshot}")
        return 0
    finally:
        if token:
            cleanup_smoke_book(api_base_url, token, smoke_book)


if __name__ == "__main__":
    raise SystemExit(main())
