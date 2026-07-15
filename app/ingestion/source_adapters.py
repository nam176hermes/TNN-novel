from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from html import unescape
from html.parser import HTMLParser
import inspect
import re
import time
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urljoin, urlparse
import os

import requests

from app.ingestion.chapter_cleaner import clean_chapter
from app.ingestion.source_policies import (
    SOURCE_POLICIES,
    SourcePolicy,
    get_source_policy,
    is_allowed_source_url,
    source_policy_public_dict,
)
from app.security.url_policy import (
    UrlPolicyViolation,
    UrlResolver,
    default_resolver,
    redacted_url,
    validate_fetch_url,
)
from app.utils.chinese_numbers import parse_chinese_number
from app.utils.proxy_pool import proxy_pool
from app.utils.stealth_browser import fetch_with_stealth_sync, PLAYWRIGHT_AVAILABLE
from app.utils.cookie_store import apply_cookies_to_session

MAX_FETCH_BYTES = 5_000_000
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_READ_TIMEOUT_SECONDS = 20
DEFAULT_TOTAL_TIMEOUT_SECONDS = 30
DEFAULT_MAX_REDIRECTS = 5


class FetchMethod(str, Enum):
    DIRECT_HTTP = "direct_http"
    STEALTH_BROWSER_HEADED = "stealth_browser_headed"
    BROWSER_SESSION = "browser_session"
    USER_VERIFICATION_REQUIRED = "user_verification_required"


class FetchErrorCode(str, Enum):
    INVALID_URL = "invalid_url"
    SOURCE_NOT_ALLOWED = "source_not_allowed"
    PRIVATE_NETWORK_BLOCKED = "private_network_blocked"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    RATE_LIMITED = "rate_limited"
    SOURCE_UNAVAILABLE = "source_unavailable"
    USER_VERIFICATION_REQUIRED = "user_verification_required"
    CONTENT_NOT_FOUND = "content_not_found"
    CONTENT_INVALID = "content_invalid"
    PARSE_FAILED = "parse_failed"
    DUPLICATE = "duplicate"
    IMPORT_FAILED = "import_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class FetchResult:
    html: str
    requested_url: str
    final_url: str
    method: FetchMethod
    status_code: int | None
    attempts: int
    elapsed_ms: int
    bytes_received: int
    cookies_refreshed: bool
    cache_hit: bool


_SECRET_DETAIL_KEYS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "passphrase",
    "api_key",
    "apikey",
    "proxy",
)


def _sanitize_error_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in (details or {}).items():
        normalized = key.casefold().replace("-", "_")
        if any(secret_key in normalized for secret_key in _SECRET_DETAIL_KEYS):
            sanitized[key] = "[redacted]"
        elif normalized.endswith("url") and isinstance(value, str):
            sanitized[key] = redacted_url(value)
        else:
            sanitized[key] = value
    return sanitized


@dataclass(frozen=True)
class SourceChapter:
    chapter_number: int
    title: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourcePreview:
    adapter_id: str
    adapter_label: str
    source: str
    source_url: str
    title: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    chapters: tuple[SourceChapter, ...] = ()
    policy: dict[str, int | str] | None = None
    bypass_used: bool = False
    bypass_method: str = ""
    fetch_method: str = ""
    fetch_status_code: int | None = None
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0
    fetch_bytes_received: int = 0
    fetch_final_url: str = ""
    fetch_cookies_refreshed: bool = False
    fetch_cache_hit: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["chapters"] = [chapter.to_dict() for chapter in self.chapters]
        data["chapter_count"] = len(self.chapters)
        return data


@dataclass(frozen=True)
class SourceChapterContent:
    adapter_id: str
    source: str
    source_url: str
    chapter_number: int
    title: str
    text: str
    fetch_method: str = ""
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0


class SourceAdapterError(ValueError):
    """Raised when a public URL cannot be handled by the source adapter layer."""

    def __init__(
        self,
        message: str,
        *,
        code: FetchErrorCode = FetchErrorCode.INTERNAL_ERROR,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        http_status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.safe_message = message
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status
        self.details = _sanitize_error_details(details)


class SourceBlockedError(SourceAdapterError):
    """Raised when a source asks the importer to stop because of cooldown or verification."""

    def __init__(
        self,
        message: str,
        *,
        code: FetchErrorCode = FetchErrorCode.USER_VERIFICATION_REQUIRED,
        retryable: bool = False,
        http_status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            retryable=retryable,
            http_status=http_status,
            details=details,
        )


def validate_public_http_url(url: str) -> str:
    return validate_source_url(url)


def _fetch_error_code_from_policy(code: str) -> FetchErrorCode:
    try:
        return FetchErrorCode(code)
    except ValueError:
        return FetchErrorCode.INTERNAL_ERROR


def validate_source_url(
    url: str,
    *,
    resolver: UrlResolver | None = None,
    allowed_domains: Iterable[str] | None = None,
) -> str:
    try:
        result = validate_fetch_url(url, resolver=resolver, allowed_domains=allowed_domains)
    except UrlPolicyViolation as exc:
        raise SourceAdapterError(
            exc.message,
            code=_fetch_error_code_from_policy(exc.code),
            retryable=exc.code == FetchErrorCode.SOURCE_UNAVAILABLE.value,
            http_status=502 if exc.code == FetchErrorCode.SOURCE_UNAVAILABLE.value else 400,
            details={"url": url},
        ) from exc
    if not is_allowed_source_url(result.canonical_url):
        raise SourceAdapterError(
            "Unsupported source domain",
            code=FetchErrorCode.SOURCE_NOT_ALLOWED,
            retryable=False,
            http_status=400,
            details={"url": result.canonical_url},
        )
    return result.canonical_url


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href_stack: list[str | None] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag != "a" or self._skip_depth:
            return
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        self._href_stack.append(self._current_href)
        self._current_href = attrs_map.get("href") or None
        self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag != "a" or self._skip_depth or self._current_href is None:
            return
        text = _normalize_inline_text("".join(self._current_text))
        if text:
            self.links.append((self._current_href, text))
        self._current_href = self._href_stack.pop() if self._href_stack else None
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._current_href is not None:
            self._current_text.append(data)


def _normalize_inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _attrs_from_tag(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(['\"])(.*?)\2", tag, re.DOTALL):
        attrs[match.group(1).casefold()] = unescape(match.group(3)).strip()
    return attrs


def _extract_meta(html: str, *names: str) -> str:
    wanted = {name.casefold() for name in names}
    for match in re.finditer(r"<meta\b[^>]*>", html, re.IGNORECASE | re.DOTALL):
        attrs = _attrs_from_tag(match.group(0))
        key = (attrs.get("name") or attrs.get("property") or "").casefold()
        if key in wanted and attrs.get("content"):
            return _normalize_inline_text(attrs["content"])
    return ""


def _strip_html_blocks(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "\n", html, flags=re.DOTALL)
    html = re.sub(r"<(?:script|style|noscript)\b.*?</(?:script|style|noscript)>", "\n", html, flags=re.I | re.S)
    return html


def _fragment_to_text(fragment: str) -> str:
    fragment = _strip_html_blocks(fragment)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(
        r"</?(?:p|div|section|article|header|footer|main|li|tr|td|h[1-6]|blockquote)\b[^>]*>",
        "\n",
        fragment,
        flags=re.I,
    )
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return unescape(fragment)


def _extract_tag_text(html: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
    return _normalize_inline_text(_fragment_to_text(match.group(1))) if match else ""


def _extract_title(html: str, source_url: str) -> str:
    title = _extract_meta(html, "og:title", "twitter:title") or _extract_tag_text(html, "h1") or _extract_tag_text(html, "title")
    title = re.split(r"\s+[-_|]\s+", title, maxsplit=1)[0].strip()
    if title:
        return title.strip("《》「」『』[]()（） ")
    parsed = urlparse(source_url)
    return parsed.netloc or source_url


def _extract_author(html: str) -> str:
    author = _extract_meta(html, "author", "book:author", "article:author")
    if author:
        return author
    text = _fragment_to_text(html[:100_000])
    match = re.search(r"(?:作者|作\s*者)\s*[:：]\s*([^\n\r\s]{1,40})", text)
    return match.group(1).strip() if match else ""


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_CHAPTER_NUMBER_RE = re.compile(
    r"(?:第\s*)?([0-9]{1,6}|[零〇一二两三四五六七八九十百千万]{1,12})\s*(?:章|节|回|卷|話|话|chapter|chương)?",
    re.IGNORECASE,
)
_CHAPTER_LINK_RE = re.compile(
    r"(第\s*[0-9零〇一二两三四五六七八九十百千万]+\s*[章节回卷話话]|"
    r"(?:chapter|chap|ch\.?|chương)\s*[0-9]+|"
    r"^[0-9]{1,5}\s*[.、:\-：]\s*.+)",
    re.IGNORECASE,
)
_JUNK_LINE_RE = re.compile(
    r"(上一章|下一章|返回目录|章节目录|书架|加入书签|最新网址|手机阅读|本章未完|点击下一页|"
    r"read\s+next|previous\s+chapter|next\s+chapter)",
    re.IGNORECASE,
)


def _parse_chapter_number(text: str, fallback: int) -> int:
    match = _CHAPTER_NUMBER_RE.search(text)
    if not match:
        return fallback
    return parse_chinese_number(match.group(1)) or fallback


def _extract_lines(html: str) -> list[str]:
    text = _fragment_to_text(html)
    raw_lines = [_normalize_inline_text(line) for line in text.splitlines()]
    lines = [line for line in raw_lines if line]
    cjk_lines = [line for line in lines if _CJK_RE.search(line) and not _JUNK_LINE_RE.search(line)]
    if len(cjk_lines) >= 3:
        return cjk_lines
    return [line for line in lines if len(line) >= 8 and not _JUNK_LINE_RE.search(line)]


def _same_site_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href)
    parsed_base = urlparse(base_url)
    parsed_absolute = urlparse(absolute)
    if parsed_absolute.scheme not in {"http", "https"}:
        return ""
    if parsed_absolute.netloc and parsed_absolute.netloc != parsed_base.netloc:
        return ""
    cleaned = parsed_absolute._replace(fragment="").geturl()
    try:
        return validate_public_http_url(cleaned)
    except SourceAdapterError:
        return ""


class GenericHtmlSourceAdapter:
    adapter_id = "generic_html"
    label = "Generic HTML"

    def supports_url(self, url: str) -> bool:
        validate_public_http_url(url)
        return True

    def preview(self, url: str) -> SourcePreview:
        fetch = fetch_public_html_result(url)
        result = self.preview_from_html(fetch.final_url, fetch.html)
        from dataclasses import replace as _replace
        return _replace(
            result,
            bypass_used=fetch.method is not FetchMethod.DIRECT_HTTP,
            bypass_method="" if fetch.method is FetchMethod.DIRECT_HTTP else fetch.method.value,
            fetch_method=fetch.method.value,
            fetch_status_code=fetch.status_code,
            fetch_attempts=fetch.attempts,
            fetch_elapsed_ms=fetch.elapsed_ms,
            fetch_bytes_received=fetch.bytes_received,
            fetch_final_url=fetch.final_url,
            fetch_cookies_refreshed=fetch.cookies_refreshed,
            fetch_cache_hit=fetch.cache_hit,
        )

    def fetch_chapter(self, url: str) -> SourceChapterContent:
        fetch = fetch_public_html_result(url)
        chapter = self.chapter_from_html(fetch.final_url, fetch.html)
        return replace(
            chapter,
            fetch_method=fetch.method.value,
            fetch_attempts=fetch.attempts,
            fetch_elapsed_ms=fetch.elapsed_ms,
        )

    def preview_from_html(self, url: str, html: str) -> SourcePreview:
        safe_url = validate_public_http_url(url)
        parser = _AnchorParser()
        parser.feed(html)

        seen_urls: set[str] = set()
        chapters: list[SourceChapter] = []
        fallback_number = 1
        for href, text in parser.links:
            if not _CHAPTER_LINK_RE.search(text):
                continue
            chapter_url = _same_site_url(safe_url, href)
            if not chapter_url or chapter_url in seen_urls:
                continue
            chapter_number = _parse_chapter_number(text, fallback_number)
            fallback_number = max(fallback_number + 1, chapter_number + 1)
            chapters.append(SourceChapter(chapter_number=chapter_number, title=text, url=chapter_url))
            seen_urls.add(chapter_url)

        chapters.sort(key=lambda chapter: (chapter.chapter_number, chapter.url))
        cover_url = _extract_meta(html, "og:image", "twitter:image")
        if cover_url:
            cover_url = urljoin(safe_url, cover_url)

        return SourcePreview(
            adapter_id=self.adapter_id,
            adapter_label=self.label,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            title=_extract_title(html, safe_url),
            author=_extract_author(html),
            description=_extract_meta(html, "description", "og:description", "twitter:description"),
            cover_url=cover_url,
            chapters=tuple(chapters),
            policy=source_policy_public_dict(safe_url),
        )

    def chapter_from_html(self, url: str, html: str) -> SourceChapterContent:
        safe_url = validate_public_http_url(url)
        h1 = _extract_tag_text(html, "h1")
        title = h1 or _extract_title(html, safe_url)
        lines = _extract_lines(html)
        text = clean_chapter("\n\n".join(lines))
        if len(text.strip()) < 20:
            raise SourceAdapterError(
                "Could not extract enough chapter text from this URL",
                code=FetchErrorCode.CONTENT_INVALID,
                retryable=False,
                http_status=422,
                details={"url": safe_url},
            )
        return SourceChapterContent(
            adapter_id=self.adapter_id,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            chapter_number=_parse_chapter_number(title, 1),
            title=title or "Chapter",
            text=text,
        )


class SelectorSourceAdapter(GenericHtmlSourceAdapter):
    def __init__(
        self,
        *,
        adapter_id: str,
        label: str,
        domains: tuple[str, ...],
        title_patterns: tuple[str, ...],
        author_patterns: tuple[str, ...] = (),
        description_patterns: tuple[str, ...] = (),
        cover_patterns: tuple[str, ...] = (),
        chapter_link_patterns: tuple[str, ...],
        content_patterns: tuple[str, ...],
    ) -> None:
        self.adapter_id = adapter_id
        self.label = label
        self.domains = domains
        self.title_patterns = title_patterns
        self.author_patterns = author_patterns
        self.description_patterns = description_patterns
        self.cover_patterns = cover_patterns
        self.chapter_link_patterns = chapter_link_patterns
        self.content_patterns = content_patterns

    def supports_url(self, url: str) -> bool:
        safe_url = validate_public_http_url(url)
        hostname = urlparse(safe_url).hostname or ""
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in self.domains)

    @staticmethod
    def _first_match(html: str, patterns: tuple[str, ...], *, normalize: bool = True) -> str:
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                text = _fragment_to_text(match.group(1))
                return _normalize_inline_text(text) if normalize else text.strip()
        return ""

    def preview_from_html(self, url: str, html: str) -> SourcePreview:
        safe_url = validate_public_http_url(url)
        chapters: list[SourceChapter] = []
        seen_urls: set[str] = set()
        fallback_number = 1
        for pattern in self.chapter_link_patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
                href = match.group(1)
                title = _normalize_inline_text(_fragment_to_text(match.group(2)))
                if not _CHAPTER_LINK_RE.search(title):
                    continue
                chapter_url = _same_site_url(safe_url, href)
                if not title or not chapter_url or chapter_url in seen_urls:
                    continue
                chapter_number = _parse_chapter_number(title, fallback_number)
                fallback_number = max(fallback_number + 1, chapter_number + 1)
                chapters.append(SourceChapter(chapter_number=chapter_number, title=title, url=chapter_url))
                seen_urls.add(chapter_url)

        if not chapters:
            return super().preview_from_html(safe_url, html)

        chapters.sort(key=lambda chapter: (chapter.chapter_number, chapter.url))
        cover_url = self._first_match(html, self.cover_patterns)
        if cover_url:
            cover_url = urljoin(safe_url, cover_url)

        return SourcePreview(
            adapter_id=self.adapter_id,
            adapter_label=self.label,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            title=self._first_match(html, self.title_patterns) or _extract_title(html, safe_url),
            author=self._first_match(html, self.author_patterns),
            description=self._first_match(html, self.description_patterns),
            cover_url=cover_url,
            chapters=tuple(chapters),
            policy=source_policy_public_dict(safe_url),
        )

    def chapter_from_html(self, url: str, html: str) -> SourceChapterContent:
        safe_url = validate_public_http_url(url)
        title = self._first_match(html, self.title_patterns) or _extract_tag_text(html, "h1") or _extract_title(html, safe_url)
        content = self._first_match(html, self.content_patterns, normalize=False)
        if not content:
            return super().chapter_from_html(safe_url, html)
        text = clean_chapter(content)
        if len(text.strip()) < 20:
            raise SourceAdapterError(
                "Could not extract enough chapter text from this URL",
                code=FetchErrorCode.CONTENT_INVALID,
                retryable=False,
                http_status=422,
                details={"url": safe_url},
            )
        return SourceChapterContent(
            adapter_id=self.adapter_id,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            chapter_number=_parse_chapter_number(title, 1),
            title=title or "Chapter",
            text=text,
        )


def raise_if_cooldown_page(url: str, html: str) -> None:
    policy = get_source_policy(url)
    if policy and policy.detects_cooldown(html[:100_000]):
        raise SourceBlockedError(
            "Source cooldown or captcha page detected; user verification is required",
            code=FetchErrorCode.USER_VERIFICATION_REQUIRED,
            retryable=False,
            http_status=409,
        )


def _decode_html_response(
    raw: bytes,
    response_encoding: str | None = None,
    apparent_encoding: str | None = None,
) -> str:
    head = raw[:4096].decode("ascii", errors="ignore")
    meta_match = re.search(r"<meta[^>]+charset=['\"]?\s*([a-zA-Z0-9_-]+)", head, re.IGNORECASE)
    latin1_encodings = {"iso-8859-1", "iso8859-1", "latin-1", "latin1"}
    response_encoding = response_encoding or ""
    apparent_encoding = apparent_encoding or ""
    late_response_encoding = response_encoding if response_encoding.strip().lower() in latin1_encodings else ""
    early_response_encoding = "" if late_response_encoding else response_encoding
    encodings = [
        meta_match.group(1) if meta_match else "",
        apparent_encoding,
        early_response_encoding,
        "utf-8",
        "gb18030",
        late_response_encoding,
    ]
    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            return raw.decode(normalized)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _raise_if_blocked_http_response(url: str, response: requests.Response) -> None:
    cf_mitigated = response.headers.get("cf-mitigated", "").casefold()
    server = response.headers.get("server", "").casefold()
    if cf_mitigated in {"challenge", "managed_challenge", "interactive"}:
        raise SourceBlockedError(
            "Source captcha or Cloudflare challenge detected; user verification is required",
            code=FetchErrorCode.USER_VERIFICATION_REQUIRED,
            retryable=False,
            http_status=409,
            details={"url": url},
        )
    if response.status_code == 429:
        raise SourceBlockedError(
            "Source rate limit detected; pause import and retry later",
            code=FetchErrorCode.RATE_LIMITED,
            retryable=True,
            http_status=429,
            details={"url": url},
        )
    if response.status_code == 403 and "cloudflare" in server:
        raise SourceBlockedError(
            "Source Cloudflare protection blocked direct preview; user verification is required",
            code=FetchErrorCode.USER_VERIFICATION_REQUIRED,
            retryable=False,
            http_status=409,
            details={"url": url},
        )


# --------------------------------------------------------------------------- #
# Browser fallback — kicked in when direct requests get blocked
# --------------------------------------------------------------------------- #

def _try_stealth_fallback(
    url: str,
    blocked_reason: str,
    timeout: int,
    requested_url: str | None = None,
    attempts: int = 0,
    started_at: float | None = None,
) -> Optional[FetchResult]:
    """If Playwright is available, retry the blocked URL via stealth browser.

    Returns rendered HTML on success; None on failure (original error re-raised
    by caller). Honors ``ENABLE_BROWSER_FALLBACK`` env var — default ON.
    """
    if os.getenv("ENABLE_BROWSER_FALLBACK", "1") == "0":
        return None
    if not PLAYWRIGHT_AVAILABLE:
        return None

    try:
        html = fetch_with_stealth_sync(url, timeout=timeout * 1000)
    except Exception as exc:  # noqa: BLE001 — surface any browser error
        # Surface the original blocked reason; fall back to None.
        import logging
        logging.getLogger(__name__).warning(
            "Stealth browser fallback failed for %s: %s", url, exc
        )
        return None

    # Cooldown check on rendered HTML — bail out if browser also saw captcha
    raise_if_cooldown_page(url, html)
    return FetchResult(
        html=html,
        requested_url=requested_url or url,
        final_url=url,
        method=FetchMethod.STEALTH_BROWSER_HEADED,
        status_code=200,
        attempts=attempts + 1,
        elapsed_ms=max(0, int((time.perf_counter() - (started_at or time.perf_counter())) * 1000)),
        bytes_received=len(html.encode("utf-8")),
        cookies_refreshed=True,
        cache_hit=False,
    )


def _call_stealth_fallback(
    url: str,
    blocked_reason: str,
    timeout: int,
    requested_url: str,
    attempts: int,
    started_at: float,
) -> FetchResult | str | None:
    """Call the fallback while tolerating old test monkeypatch signatures."""
    try:
        parameter_count = len(inspect.signature(_try_stealth_fallback).parameters)
    except (TypeError, ValueError):
        parameter_count = 6
    if parameter_count <= 3:
        return _try_stealth_fallback(url, blocked_reason, timeout)  # type: ignore[misc,call-arg]
    return _try_stealth_fallback(url, blocked_reason, timeout, requested_url, attempts, started_at)


def fetch_public_html_result(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_proxy_attempts: int = 3,
    *,
    allow_browser_fallback: bool = True,
    resolver: UrlResolver | None = default_resolver,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_response_bytes: int = MAX_FETCH_BYTES,
    connect_timeout: int | None = None,
    read_timeout: int | None = None,
    total_timeout: int | None = None,
) -> FetchResult:
    requested_url = url
    started_at = time.perf_counter()
    attempts = 0
    current_url = validate_source_url(url, resolver=resolver)
    original_policy = get_source_policy(current_url)
    original_domains = original_policy.domains if original_policy else None
    connect_timeout = connect_timeout if connect_timeout is not None else min(timeout, DEFAULT_CONNECT_TIMEOUT_SECONDS)
    read_timeout = read_timeout if read_timeout is not None else timeout
    total_timeout = total_timeout if total_timeout is not None else max(timeout, DEFAULT_TOTAL_TIMEOUT_SECONDS)
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }

    # Apply saved cookies (from previous stealth browser session)
    apply_cookies_to_session(current_url, session)

    # Get proxy from pool if available
    proxies = None
    if proxy_pool.count > 0:
        proxy = proxy_pool.get_next()
        if proxy:
            proxies = {"http": proxy.url, "https": proxy.url}
            if proxy.username and proxy.password:
                proxies["http"] = f"http://{proxy.username}:{proxy.password}@{proxy.url.split('://')[-1]}"
                proxies["https"] = proxies["http"]
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

    proxy_attempts = 0
    redirects_followed = 0
    while True:
        if time.perf_counter() - started_at > total_timeout:
            raise SourceAdapterError(
                "Source fetch exceeded total timeout",
                code=FetchErrorCode.READ_TIMEOUT,
                retryable=True,
                http_status=504,
                details={"url": current_url},
            )
        try:
            attempts += 1
            response = session.get(
                current_url,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
                allow_redirects=False,
                stream=True,
                proxies=proxies,
            )
        except requests.exceptions.ConnectTimeout as e:
            if proxy and proxies:
                proxy_pool.mark_healthy(proxy.url, False)
            raise SourceAdapterError(
                "Source connection timed out",
                code=FetchErrorCode.CONNECT_TIMEOUT,
                retryable=True,
                http_status=504,
                details={"url": current_url},
            ) from e
        except requests.exceptions.ReadTimeout as e:
            raise SourceAdapterError(
                "Source read timed out",
                code=FetchErrorCode.READ_TIMEOUT,
                retryable=True,
                http_status=504,
                details={"url": current_url},
            ) from e
        except requests.exceptions.ProxyError as e:
            # Mark proxy as unhealthy, retry without proxy or with next one
            if proxy and proxies:
                proxy_pool.mark_healthy(proxy.url, False)
                proxy_attempts += 1
                if proxy_attempts >= max_proxy_attempts:
                    raise SourceAdapterError(
                        f"Proxy failed after {max_proxy_attempts} attempts",
                        code=FetchErrorCode.SOURCE_UNAVAILABLE,
                        retryable=True,
                        http_status=502,
                        details={"url": current_url, "proxy": getattr(proxy, "url", "")},
                    ) from e
                # Try next proxy
                proxy = proxy_pool.get_next()
                if proxy:
                    proxies = {"http": proxy.url, "https": proxy.url}
                    if proxy.username and proxy.password:
                        proxies["http"] = f"http://{proxy.username}:{proxy.password}@{proxy.url.split('://')[-1]}"
                        proxies["https"] = proxies["http"]
                continue
            raise SourceAdapterError(
                "Source connection failed",
                code=FetchErrorCode.SOURCE_UNAVAILABLE,
                retryable=True,
                http_status=502,
                details={"url": current_url},
            ) from e
        except requests.exceptions.RequestException as e:
            raise SourceAdapterError(
                "Source request failed",
                code=FetchErrorCode.SOURCE_UNAVAILABLE,
                retryable=True,
                http_status=502,
                details={"url": current_url},
            ) from e

        if 300 <= response.status_code < 400 and response.headers.get("Location"):
            if redirects_followed >= max_redirects:
                raise SourceAdapterError(
                    "Too many redirects while fetching source URL",
                    code=FetchErrorCode.SOURCE_UNAVAILABLE,
                    retryable=False,
                    http_status=508,
                    details={"url": current_url},
                )
            try:
                next_url = validate_source_url(
                    urljoin(current_url, response.headers["Location"]),
                    resolver=resolver,
                    allowed_domains=original_domains,
                )
            except SourceAdapterError as exc:
                if exc.code is FetchErrorCode.SOURCE_NOT_ALLOWED:
                    raise SourceAdapterError(
                        "Source redirect changed to a different supported source",
                        code=FetchErrorCode.SOURCE_NOT_ALLOWED,
                        retryable=False,
                        http_status=400,
                        details={"url": current_url, "redirect": response.headers["Location"]},
                    ) from exc
                raise
            next_policy = get_source_policy(next_url)
            if original_policy and (not next_policy or next_policy.source_id != original_policy.source_id):
                raise SourceAdapterError(
                    "Source redirect changed to a different supported source",
                    code=FetchErrorCode.SOURCE_NOT_ALLOWED,
                    retryable=False,
                    http_status=400,
                    details={"url": current_url, "redirect": next_url},
                )
            redirects_followed += 1
            current_url = next_url
            continue

        try:
            _raise_if_blocked_http_response(current_url, response)
        except SourceBlockedError as e:
            # Browser fallback on blocked responses
            if allow_browser_fallback:
                fallback = _call_stealth_fallback(current_url, str(e), timeout, requested_url, attempts, started_at)
                if isinstance(fallback, FetchResult):
                    return fallback
                if isinstance(fallback, str):
                    return FetchResult(
                        html=fallback,
                        requested_url=requested_url,
                        final_url=current_url,
                        method=FetchMethod.STEALTH_BROWSER_HEADED,
                        status_code=200,
                        attempts=attempts + 1,
                        elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                        bytes_received=len(fallback.encode("utf-8")),
                        cookies_refreshed=True,
                        cache_hit=False,
                    )
            raise

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 404:
                code = FetchErrorCode.CONTENT_NOT_FOUND
                retryable = False
            elif response.status_code >= 500:
                code = FetchErrorCode.SOURCE_UNAVAILABLE
                retryable = True
            else:
                code = FetchErrorCode.SOURCE_UNAVAILABLE
                retryable = False
            raise SourceAdapterError(
                "Source returned an unsuccessful HTTP status",
                code=code,
                retryable=retryable,
                http_status=response.status_code,
                details={"url": current_url, "status_code": response.status_code},
            ) from e
        content_type = response.headers.get("Content-Type", "")
        if content_type and not any(kind in content_type.lower() for kind in ("text/", "html", "xml")):
            raise SourceAdapterError(
                f"Unsupported content type: {content_type}",
                code=FetchErrorCode.CONTENT_INVALID,
                retryable=False,
                http_status=415,
                details={"url": current_url, "content_type": content_type},
            )

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_response_bytes:
                raise SourceAdapterError(
                    "Source URL response is too large",
                    code=FetchErrorCode.CONTENT_INVALID,
                    retryable=False,
                    http_status=413,
                    details={"url": current_url},
            )
            chunks.append(chunk)
            if time.perf_counter() - started_at > total_timeout:
                raise SourceAdapterError(
                    "Source fetch exceeded total timeout",
                    code=FetchErrorCode.READ_TIMEOUT,
                    retryable=True,
                    http_status=504,
                    details={"url": current_url},
                )
        raw = b"".join(chunks)
        text = _decode_html_response(raw, response.encoding, getattr(response, "apparent_encoding", None))
        raise_if_cooldown_page(current_url, text)
        return FetchResult(
            html=text,
            requested_url=requested_url,
            final_url=current_url,
            method=FetchMethod.DIRECT_HTTP,
            status_code=response.status_code,
            attempts=attempts,
            elapsed_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            bytes_received=len(raw),
            cookies_refreshed=False,
            cache_hit=False,
        )


def fetch_public_html(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_proxy_attempts: int = 3,
    *,
    allow_browser_fallback: bool = True,
    resolver: UrlResolver | None = default_resolver,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_response_bytes: int = MAX_FETCH_BYTES,
    connect_timeout: int | None = None,
    read_timeout: int | None = None,
    total_timeout: int | None = None,
) -> str:
    """Compatibility wrapper returning only HTML.

    Deprecated for internal callers: use ``fetch_public_html_result`` so fetch
    metadata is carried with the HTML instead of via side channels.
    """
    return fetch_public_html_result(
        url,
        timeout=timeout,
        max_proxy_attempts=max_proxy_attempts,
        allow_browser_fallback=allow_browser_fallback,
        resolver=resolver,
        max_redirects=max_redirects,
        max_response_bytes=max_response_bytes,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        total_timeout=total_timeout,
    ).html


class SourceAdapterRegistry:
    def __init__(self, adapters: Iterable[GenericHtmlSourceAdapter] | None = None):
        self.adapters = list(adapters or [GenericHtmlSourceAdapter()])

    def get_for_url(self, url: str) -> GenericHtmlSourceAdapter:
        for adapter in self.adapters:
            if adapter.supports_url(url):
                return adapter
        raise SourceAdapterError("No source adapter supports this URL")

    def preview(self, url: str) -> SourcePreview:
        return self.get_for_url(url).preview(url)

    def fetch_chapter(self, url: str) -> SourceChapterContent:
        return self.get_for_url(url).fetch_chapter(url)


def build_default_source_adapters() -> list[GenericHtmlSourceAdapter]:
    chapter_link_pattern = (
        r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*'
        r'([^<]*(?:第\s*[0-9零〇一二两三四五六七八九十百千万]+\s*[章节回卷話话][^<]*)?)</a>'
    )
    return [
        SelectorSourceAdapter(
            adapter_id="69shuba",
            label="69shuba",
            domains=("69shuba.com", "69shuba.cx", "69shux.com"),
            title_patterns=(r"<h1[^>]*>(.*?)</h1>", r'<meta property="og:title" content="([^"]+)"'),
            author_patterns=(r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})",),
            description_patterns=(
                r'<meta name="description" content="([^"]+)"',
                r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',
            ),
            cover_patterns=(r'<meta property="og:image" content="([^"]+)"', r'<img[^>]+src="([^"]+)"[^>]+(?:cover|bookimg|fmimg)'),
            chapter_link_patterns=(chapter_link_pattern,),
            content_patterns=(
                r'<div[^>]+class="container"[^>]*>(.*?)</div>\s*<div[^>]+class="(?:bottom|foot|pagefoot)',
                r'<div[^>]+class="[^"]*txtnav[^"]*"[^>]*>(.*?)</div>\s*<div',
                r'<div[^>]+id="content"[^>]*>(.*?)</div>',
                r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            ),
        ),
        SelectorSourceAdapter(
            adapter_id="69shumi",
            label="69shumi",
            domains=("69shumi.net", "69shumi.com"),
            title_patterns=(r'<h1[^>]+class="[^"]*bookTitle[^"]*"[^>]*>(.*?)</h1>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<p[^>]+class="[^"]*booktag[^"]*"[^>]*>(.*?)</p>',),
            description_patterns=(r'<p[^>]+id="bookIntro"[^>]*>(.*?)</p>',),
            cover_patterns=(r'<div[^>]+class="[^"]*col-sm-2[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<dd[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+id="booktxt"[^>]*>(.*?)</div>', r'<div[^>]+id="content"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="biquge",
            label="Biquge",
            domains=("biquge.tw", "22biqu.com"),
            title_patterns=(r"<h1[^>]*>(.*?)</h1>", r'<meta property="og:title" content="([^"]+)"'),
            author_patterns=(r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})",),
            description_patterns=(
                r'<meta name="description" content="([^"]+)"',
                r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',
            ),
            cover_patterns=(r'<meta property="og:image" content="([^"]+)"', r'<img[^>]+src="([^"]+)"'),
            chapter_link_patterns=(chapter_link_pattern,),
            content_patterns=(
                r'<div[^>]+id="chaptercontent"[^>]*>(.*?)</div>',
                r'<div[^>]+id="content"[^>]*>(.*?)</div>',
                r'<div[^>]+class="[^"]*read-content[^"]*"[^>]*>(.*?)</div>',
            ),
        ),
        SelectorSourceAdapter(
            adapter_id="uukanshu",
            label="Uukanshu",
            domains=("uukanshu.cc",),
            title_patterns=(r'<h1[^>]+class="[^"]*booktitle[^"]*"[^>]*>(.*?)</h1>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})",),
            description_patterns=(r'<meta name="description" content="([^"]+)"',),
            cover_patterns=(r'<meta property="og:image" content="([^"]+)"', r'<img[^>]+src="([^"]+)"'),
            chapter_link_patterns=(chapter_link_pattern,),
            content_patterns=(r'<div[^>]+id="contentbox"[^>]*>(.*?)</div>', r'<div[^>]+id="content"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="17k",
            label="17K",
            domains=("17k.com",),
            title_patterns=(r"<h1[^>]*>(.*?)</h1>",),
            author_patterns=(r'<a[^>]+class="[^"]*name[^"]*"[^>]*>(.*?)</a>', r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})"),
            description_patterns=(r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"[^>]+(?:cover|BookInfo)',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]*/chapter/[^"]+)"[^>]*>\s*(?:<span[^>]*>)?([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*readAreaBox content[^"]*"[^>]*>(.*?)</div>', r'<div[^>]+class="[^"]*\bp\b[^"]*"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="52shuku",
            label="52shuku",
            domains=("52shuku.net",),
            title_patterns=(r"<h1[^>]*>(.*?)</h1>",),
            author_patterns=(r'<a[^>]+class="[^"]*info[^"]*"[^>]*>(.*?)</a>',),
            description_patterns=(r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<li[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<article[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</article>', r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="fanqienovel",
            label="Fanqie Novel",
            domains=("fanqienovel.com",),
            title_patterns=(r'<meta property="og:novel:book_name" content="([^"]+)"', r'<meta property="og:title" content="([^"]+)"'),
            author_patterns=(r'<meta property="og:novel:author" content="([^"]+)"', r'<span[^>]+class="[^"]*info-author[^"]*"[^>]*>(.*?)</span>'),
            description_patterns=(r'<meta name="description" content="([^"]+)"',),
            cover_patterns=(r'<meta property="og:image" content="([^"]+)"',),
            chapter_link_patterns=(r'<a[^>]+href="(/reader/[^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*muye-reader-content[^"]*"[^>]*>(.*?)</div>',),
        ),
        SelectorSourceAdapter(
            adapter_id="jjwxc",
            label="JJWXC",
            domains=("jjwxc.net",),
            title_patterns=(r"<h1[^>]*>(.*?)</h1>",),
            author_patterns=(r'<a[^>]+href="[^"]*oneauthor\.php[^"]*"[^>]*>(.*?)</a>',),
            description_patterns=(r'<meta name="description" content="([^"]+)"',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"[^>]+(?:width|cover)',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]*novelid=\d+&chapterid=\d+[^"]*)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*noveltext[^"]*"[^>]*>(.*?)</div>', r'<div[^>]+class="[^"]*read-content[^"]*"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="qidian",
            label="Qidian",
            domains=("qidian.com",),
            title_patterns=(r'<meta property="og:novel:book_name" content="([^"]+)"', r'<meta property="og:title" content="([^"]+)"', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<meta property="og:novel:author" content="([^"]+)"', r'<a[^>]+class="[^"]*author[^"]*"[^>]*>(.*?)</a>'),
            description_patterns=(r'<meta name="description" content="([^"]+)"',),
            cover_patterns=(r'<meta property="og:image" content="([^"]+)"',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]*/chapter/[^"]+)"[^>]*>([^<]+)', r'<a[^>]+href="([^"]+)"[^>]+data-bid[^>]*>([^<]+)'),
            content_patterns=(r'<div[^>]+class="[^"]*read-content[^"]*"[^>]*>(.*?)</div>', r'<div[^>]+class="[^"]*j_readContent[^"]*"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="novel543",
            label="Novel543",
            domains=("novel543.com",),
            title_patterns=(r'<h1[^>]+class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<span[^>]+class="[^"]*author[^"]*"[^>]*>(.*?)</span>',),
            description_patterns=(r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<div[^>]+class="[^"]*cover[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<li[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',),
        ),
        SelectorSourceAdapter(
            adapter_id="hetushu",
            label="Hetushu",
            domains=("hetushu.com",),
            title_patterns=(r'<h2[^>]*>(.*?)</h2>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<a[^>]+href="[^"]*/author/[^"]*"[^>]*>(.*?)</a>',),
            description_patterns=(r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]+/chapter_\d+\.html)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+id="content"[^>]*>(.*?)</div>',),
        ),
        SelectorSourceAdapter(
            adapter_id="ixdzs8",
            label="Ixdzs8",
            domains=("ixdzs8.com", "ixdzs.com"),
            title_patterns=(r'<h1[^>]*>(.*?)</h1>',),
            author_patterns=(r'<a[^>]+class="[^"]*bauthor[^"]*"[^>]*>(.*?)</a>',),
            description_patterns=(r'<div[^>]+id="intro"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]+/chapter_[^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',),
        ),
        SelectorSourceAdapter(
            adapter_id="xbanxia",
            label="Xbanxia",
            domains=("xbanxia.cc", "xbanxia.com"),
            title_patterns=(r'<div[^>]+class="[^"]*book-describe[^"]*"[^>]*>\s*<h1[^>]*>(.*?)</h1>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<div[^>]+class="[^"]*book-describe[^"]*"[^>]*>\s*<p[^>]*>\s*<a[^>]*>(.*?)</a>',),
            description_patterns=(r'<div[^>]+class="[^"]*describe-html[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<div[^>]+class="[^"]*book-img[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"',),
            chapter_link_patterns=(r'<li[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+id="content"[^>]*>(.*?)</div>', r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>'),
        ),
        SelectorSourceAdapter(
            adapter_id="bookqq",
            label="Book QQ",
            domains=("book.qq.com",),
            title_patterns=(r'<h1[^>]+class="[^"]*book-title[^"]*"[^>]*>(.*?)</h1>', r"<h1[^>]*>(.*?)</h1>"),
            author_patterns=(r'<span[^>]+class="[^"]*author[^"]*"[^>]*>(.*?)</span>',),
            description_patterns=(r'<div[^>]+class="[^"]*book-intro[^"]*"[^>]*>(.*?)</div>',),
            cover_patterns=(r'<img[^>]+src="([^"]+)"[^>]+(?:book-cover|cover)',),
            chapter_link_patterns=(r'<a[^>]+href="([^"]+/chapter/[^"]+)"[^>]*>([^<]+)',),
            content_patterns=(r'<div[^>]+class="[^"]*read-content[^"]*"[^>]*>(.*?)</div>',),
        ),
        GenericHtmlSourceAdapter(),
    ]


_DEFAULT_REGISTRY = SourceAdapterRegistry(build_default_source_adapters())


def get_source_registry() -> SourceAdapterRegistry:
    return _DEFAULT_REGISTRY


def _adapter_domains(adapter: GenericHtmlSourceAdapter) -> tuple[str, ...]:
    domains = getattr(adapter, "domains", ())
    return tuple(domains) if isinstance(domains, tuple) else tuple(domains or ())


def _adapter_matches_policy(adapter: GenericHtmlSourceAdapter, policy: SourcePolicy) -> bool:
    domains = _adapter_domains(adapter)
    return any(domain in domains for domain in policy.domains)


def list_source_capabilities() -> list[dict[str, object]]:
    adapters = [adapter for adapter in build_default_source_adapters() if _adapter_domains(adapter)]
    capabilities: list[dict[str, object]] = []

    for policy in SOURCE_POLICIES:
        adapter = next((candidate for candidate in adapters if _adapter_matches_policy(candidate, policy)), None)
        has_selector = adapter is not None
        adapter_id = adapter.adapter_id if adapter else GenericHtmlSourceAdapter.adapter_id
        adapter_label = adapter.label if adapter else GenericHtmlSourceAdapter.label

        capabilities.append(
            {
                "source_id": policy.source_id,
                "label": policy.label,
                "domains": list(policy.domains),
                "adapter_id": adapter_id,
                "adapter_label": adapter_label,
                "extraction": "selector" if has_selector else "generic",
                "direct_import": True,
                "delay_seconds": policy.delay_seconds,
                "max_concurrency": policy.max_concurrency,
                "retry_limit": policy.retry_limit,
                "notes": (
                    "Parser rieng cho layout hien tai."
                    if has_selector
                    else "Dung parser HTML chung; co the can browser helper khi trang chan direct fetch."
                ),
            }
        )

    return capabilities
