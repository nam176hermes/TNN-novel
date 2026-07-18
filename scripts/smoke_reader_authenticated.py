#!/usr/bin/env python3
"""Run an authenticated, read-only Reader API smoke test.

The only non-GET request is ``/api/auth/login``, which is necessary to obtain
the bearer token.  Every Reader request after that login is a GET; this script
does not seed, edit, export, or delete production data.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit


DEFAULT_API_BASE_URL = "http://127.0.0.1:7860"
USER_AGENT = "novel-pipeline-reader-readonly-smoke/1.0"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class ReaderSmokeResult:
    book_id: int
    chapter_id: int
    translation_characters: int


def validate_api_base_url(api_base_url: str) -> str:
    """Return a safe endpoint; public Reader smoke traffic must use HTTPS."""
    normalized = api_base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--base-url must not contain credentials, a query, or a fragment")
    if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("HTTPS is required for a non-loopback Reader endpoint")
    return normalized


def _read_password(password_file: Path) -> str:
    try:
        mode = stat.S_IMODE(password_file.stat().st_mode)
    except OSError as exc:
        raise ValueError(f"cannot read password file: {exc}") from exc
    if mode & 0o077:
        raise ValueError("password file permissions must be 0600 or stricter")
    password = password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("password file is empty")
    return password


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 10.0,
) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {url} returned invalid JSON") from exc


def _positive_id(value: Any, *, field: str) -> int:
    try:
        identifier = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Reader response did not include a valid {field}") from exc
    if identifier <= 0:
        raise RuntimeError(f"Reader response did not include a valid {field}")
    return identifier


def _select_book(library: Any, requested_book_id: int | None) -> int:
    if requested_book_id is not None:
        return requested_book_id
    if not isinstance(library, dict) or not isinstance(library.get("books"), list):
        raise RuntimeError("library response did not include books")
    for book in library["books"]:
        if isinstance(book, dict):
            try:
                return _positive_id(book.get("id"), field="book id")
            except RuntimeError:
                continue
    raise RuntimeError("no translated Reader book is available for smoke testing")


def _select_chapter(chapters: Any, requested_chapter_id: int | None) -> int:
    if not isinstance(chapters, list):
        raise RuntimeError("chapter response was not a list")
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        chapter_id = _positive_id(chapter.get("id"), field="chapter id")
        if requested_chapter_id is not None:
            if chapter_id == requested_chapter_id:
                return chapter_id
            continue
        if chapter.get("translated_text_path") == "available" or str(chapter.get("status") or "") in {
            "translated",
            "audio_done",
        }:
            return chapter_id
    if requested_chapter_id is not None:
        raise RuntimeError("requested chapter is not part of the requested book")
    raise RuntimeError("no translated Reader chapter is available for smoke testing")


def run_authenticated_reader_smoke(
    *,
    api_base_url: str,
    username: str,
    password: str,
    book_id: int | None = None,
    chapter_id: int | None = None,
    timeout: float = 10.0,
    request: Callable[..., Any] = request_json,
) -> ReaderSmokeResult:
    """Authenticate once and verify a translated Reader chapter via GETs only."""
    base_url = validate_api_base_url(api_base_url)
    resolved_username = username.strip()
    if not resolved_username or not password:
        raise ValueError("username and password are required")

    login_response = request(
        "POST",
        f"{base_url}/api/auth/login",
        payload={"username": resolved_username, "password": password},
        timeout=timeout,
    )
    if not isinstance(login_response, dict) or not isinstance(login_response.get("access_token"), str):
        raise RuntimeError("login response did not include an access token")
    token = login_response["access_token"]
    if not token:
        raise RuntimeError("login response did not include an access token")

    library = request("GET", f"{base_url}/api/library/books", token=token, timeout=timeout)
    resolved_book_id = _select_book(library, book_id)
    chapters = request(
        "GET",
        f"{base_url}/api/books/{resolved_book_id}/chapters",
        token=token,
        timeout=timeout,
    )
    resolved_chapter_id = _select_chapter(chapters, chapter_id)
    request(
        "GET",
        f"{base_url}/api/books/{resolved_book_id}/reader/state",
        token=token,
        timeout=timeout,
    )
    chapter = request(
        "GET",
        f"{base_url}/api/books/{resolved_book_id}/chapters/{resolved_chapter_id}",
        token=token,
        timeout=timeout,
    )
    if not isinstance(chapter, dict) or _positive_id(chapter.get("book_id"), field="chapter book id") != resolved_book_id:
        raise RuntimeError("Reader chapter did not belong to the requested book")
    translation = request(
        "GET",
        f"{base_url}/api/books/{resolved_book_id}/chapters/{resolved_chapter_id}/translation",
        token=token,
        timeout=timeout,
    )
    if not isinstance(translation, dict) or translation.get("missing") is not False:
        raise RuntimeError("Reader translation is missing")
    text = translation.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Reader translation is empty")
    return ReaderSmokeResult(
        book_id=resolved_book_id,
        chapter_id=resolved_chapter_id,
        translation_characters=len(text),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authenticated read-only Reader API smoke test")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_READER_BASE_URL", DEFAULT_API_BASE_URL))
    parser.add_argument("--username", default=os.getenv("SMOKE_READER_USERNAME", ""))
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--book-id", type=int)
    parser.add_argument("--chapter-id", type=int)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        password = _read_password(args.password_file)
        result = run_authenticated_reader_smoke(
            api_base_url=args.base_url,
            username=args.username,
            password=password,
            book_id=args.book_id,
            chapter_id=args.chapter_id,
            timeout=args.timeout,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"FAIL authenticated read-only Reader smoke: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS authenticated read-only Reader smoke "
        f"book_id={result.book_id} chapter_id={result.chapter_id} "
        f"translation_characters={result.translation_characters}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
