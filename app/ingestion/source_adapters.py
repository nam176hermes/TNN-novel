from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from html import unescape
from html.parser import HTMLParser
import inspect
import logging
import re
import time
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urljoin, urlparse
import os

import requests

from app.ingestion.chapter_cleaner import clean_chapter
from app.ingestion.dom_parser import (
    DomParserError,
    DomParserFramework,
    DomSelector,
    DomSelectorConfig,
)
from app.ingestion.source_policies import (
    SOURCE_POLICIES,
    SourcePolicy,
    get_source_policy,
    is_allowed_source_url,
    source_policy_public_dict,
)
from app.ingestion.text_normalization import normalize_import_text, source_hash
from app.observability import default_observability
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

logger = logging.getLogger(__name__)


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
    adapter_version: str = ""
    parser_method: str = ""

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
    fetch_bytes_received: int = 0
    content_hash: str = ""
    adapter_version: str = ""
    parser_method: str = ""


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
        retry_after_seconds: float | None = None,
        http_status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
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
    r"^[0-9]{1,4}\s*[.、]\s*.+)",  # Tightened: 1-4 digits + dot/ideographic comma only
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

    def transform_preview_url(self, url: str) -> str:
        """Rewrite the URL before fetching preview HTML.

        Override in subclasses for sites where the book-info page
        (e.g. ``/book/123.htm``) only shows a few latest chapters while
        the full list lives at a different path (e.g. ``/book/123/``).
        Default: return as-is.
        """
        return url

    def preview(self, url: str) -> SourcePreview:
        url = self.transform_preview_url(url)
        try:
            fetch = fetch_public_html_result(url)
            result = self.preview_from_html(fetch.final_url, fetch.html)
        except SourceAdapterError as exc:
            default_observability.record_fetch(
                adapter_id=self.adapter_id,
                adapter_version=getattr(self, "adapter_version", ""),
                fetch_method="direct_http",
                error_code=exc.code.value,
                operation="preview",
            )
            raise
        default_observability.record_fetch(
            adapter_id=self.adapter_id,
            adapter_version=getattr(self, "adapter_version", ""),
            fetch_method=fetch.method.value,
            elapsed_ms=fetch.elapsed_ms,
            response_bytes=fetch.bytes_received,
            operation="preview",
        )
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
        try:
            fetch = fetch_public_html_result(url)
            chapter = self.chapter_from_html(fetch.final_url, fetch.html)
        except SourceAdapterError as exc:
            default_observability.record_fetch(
                adapter_id=self.adapter_id,
                adapter_version=getattr(self, "adapter_version", ""),
                fetch_method="direct_http",
                error_code=exc.code.value,
                operation="fetch_chapter",
            )
            raise
        default_observability.record_fetch(
            adapter_id=self.adapter_id,
            adapter_version=getattr(self, "adapter_version", ""),
            fetch_method=fetch.method.value,
            elapsed_ms=fetch.elapsed_ms,
            response_bytes=fetch.bytes_received,
            parsed_text_length=len(chapter.text),
            operation="fetch_chapter",
        )
        return replace(
            chapter,
            fetch_method=fetch.method.value,
            fetch_attempts=fetch.attempts,
            fetch_elapsed_ms=fetch.elapsed_ms,
            fetch_bytes_received=fetch.bytes_received,
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


class _DomFallbackRequired(SourceAdapterError):
    """Internal marker for a selector mismatch that may use the legacy parser."""


class DomSourceAdapter(GenericHtmlSourceAdapter):
    """Versioned DOM adapter with an explicit, safe legacy-regex fallback."""

    def __init__(
        self,
        *,
        adapter_id: str,
        label: str,
        domains: tuple[str, ...],
        selectors: DomSelectorConfig,
        adapter_version: str,
        regex_fallback: SelectorSourceAdapter | None = None,
    ) -> None:
        if not domains:
            raise ValueError("DOM source adapter requires at least one allowed domain")
        self.adapter_id = adapter_id
        self.label = label
        self.domains = domains
        self.adapter_version = adapter_version
        self.selectors = selectors
        self._dom_parser = DomParserFramework(selectors)
        self._regex_fallback = regex_fallback

    def supports_url(self, url: str) -> bool:
        safe_url = validate_public_http_url(url)
        return self.domain_policy(safe_url)

    def domain_policy(self, url: str) -> bool:
        try:
            hostname = urlparse(validate_public_http_url(url)).hostname or ""
        except SourceAdapterError:
            return False
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in self.domains)

    def canonicalize_url(self, url: str, *, base_url: str | None = None) -> str:
        absolute = urljoin(base_url, url) if base_url else url
        return validate_source_url(absolute, allowed_domains=self.domains)

    def transform_preview_url(self, url: str) -> str:
        """Rewrite book-info URLs to chapter-list URLs for 69shuba/69shumi.

        ``/book/123.htm`` → ``/book/123/`` (full chapter list page).
        """
        if self.adapter_id in ("69shuba", "69shumi"):
            # /book/123.htm → /book/123/
            import re

            m = re.match(r"^(https?://[^/]+/book/\d+)\.htm$", url)
            if m:
                return m.group(1) + "/"
        return url

    @staticmethod
    def normalize_cleanup(text: str) -> str:
        return DomParserFramework.normalize_cleanup(text)

    def validate_content(self, text: str, *, html: str = "") -> None:
        try:
            if html:
                self._dom_parser.raise_for_page_state(html)
            self._dom_parser.validate_content(text)
        except DomParserError as exc:
            raise self._source_error(exc) from exc

    def parse_preview(self, url: str, html: str) -> SourcePreview:
        safe_url = self.canonicalize_url(url)
        try:
            parsed = self._dom_parser.parse_preview(
                base_url=safe_url,
                html=html,
                canonicalize_link=lambda value: self.canonicalize_url(value, base_url=safe_url),
            )
        except DomParserError as exc:
            default_observability.record_parse(
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                operation="preview",
                error_code=exc.code,
            )
            raise self._source_error(exc, safe_url) from exc

        chapters: list[SourceChapter] = []
        fallback_number = 1
        for title, chapter_url in parsed.chapter_links:
            if not _CHAPTER_LINK_RE.search(title):
                continue
            chapter_number = _parse_chapter_number(title, fallback_number)
            fallback_number = max(fallback_number + 1, chapter_number + 1)
            chapters.append(SourceChapter(chapter_number=chapter_number, title=title, url=chapter_url))
        if not chapters:
            raise _DomFallbackRequired(
                "DOM parser did not find valid chapter links",
                code=FetchErrorCode.PARSE_FAILED,
                retryable=False,
                http_status=422,
                details={"url": safe_url},
            )
        chapters.sort(key=lambda chapter: (chapter.chapter_number, chapter.url))
        result = SourcePreview(
            adapter_id=self.adapter_id,
            adapter_label=self.label,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            title=parsed.title,
            author=parsed.author,
            description=parsed.description,
            cover_url=self._safe_asset_url(parsed.cover_url),
            chapters=tuple(chapters),
            policy=source_policy_public_dict(safe_url),
            adapter_version=self.adapter_version,
            parser_method="dom",
        )
        default_observability.record_parse(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            operation="preview",
        )
        return result

    def parse_chapter(self, url: str, html: str) -> SourceChapterContent:
        safe_url = self.canonicalize_url(url)
        try:
            parsed = self._dom_parser.parse_chapter(html=html)
        except DomParserError as exc:
            default_observability.record_parse(
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                operation="chapter",
                error_code=exc.code,
            )
            raise self._source_error(exc, safe_url) from exc
        title = parsed.title or _extract_title(html, safe_url)
        result = SourceChapterContent(
            adapter_id=self.adapter_id,
            source=urlparse(safe_url).netloc,
            source_url=safe_url,
            chapter_number=_parse_chapter_number(title, 1),
            title=title or "Chapter",
            text=parsed.text,
            content_hash=parsed.content_hash,
            adapter_version=self.adapter_version,
            parser_method="dom",
        )
        default_observability.record_parse(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            operation="chapter",
            parsed_text_length=len(parsed.text),
        )
        return result

    def preview_from_html(self, url: str, html: str) -> SourcePreview:
        try:
            return self.parse_preview(url, html)
        except _DomFallbackRequired:
            if self._regex_fallback is None:
                raise
            self._log_regex_fallback("preview")
            fallback = self._regex_fallback.preview_from_html(self.canonicalize_url(url), html)
            return replace(
                fallback,
                cover_url=self._safe_asset_url(fallback.cover_url),
                adapter_version=self.adapter_version,
                parser_method="regex_fallback",
            )

    def chapter_from_html(self, url: str, html: str) -> SourceChapterContent:
        try:
            return self.parse_chapter(url, html)
        except _DomFallbackRequired:
            if self._regex_fallback is None:
                raise
            self._log_regex_fallback("chapter")
            fallback = self._regex_fallback.chapter_from_html(self.canonicalize_url(url), html)
            normalized = normalize_import_text(fallback.text)
            try:
                self._dom_parser.raise_for_page_state(html)
                self._dom_parser.validate_content(normalized, title=fallback.title)
            except DomParserError as exc:
                raise self._source_error(exc, self.canonicalize_url(url)) from exc
            return replace(
                fallback,
                text=normalized,
                content_hash=source_hash(normalized),
                adapter_version=self.adapter_version,
                parser_method="regex_fallback",
            )

    def _log_regex_fallback(self, target: str) -> None:
        logger.warning(
            "dom_parser_fallback adapter=%s version=%s target=%s",
            self.adapter_id,
            self.adapter_version,
            target,
        )

    @staticmethod
    def _safe_asset_url(url: str) -> str:
        if not url:
            return ""
        try:
            return validate_fetch_url(url, resolver=None).canonical_url
        except UrlPolicyViolation:
            return ""

    @staticmethod
    def _source_error(exc: DomParserError, url: str = "") -> SourceAdapterError:
        try:
            code = FetchErrorCode(exc.code)
        except ValueError:
            code = FetchErrorCode.PARSE_FAILED
        error_type: type[SourceAdapterError]
        if code is FetchErrorCode.USER_VERIFICATION_REQUIRED:
            error_type = SourceBlockedError
        elif code is FetchErrorCode.PARSE_FAILED and exc.fallback_allowed:
            error_type = _DomFallbackRequired
        else:
            error_type = SourceAdapterError
        status_by_code = {
            FetchErrorCode.USER_VERIFICATION_REQUIRED: 409,
            FetchErrorCode.RATE_LIMITED: 429,
            FetchErrorCode.SOURCE_UNAVAILABLE: 502,
            FetchErrorCode.CONTENT_NOT_FOUND: 404,
            FetchErrorCode.CONTENT_INVALID: 422,
            FetchErrorCode.PARSE_FAILED: 422,
        }
        return error_type(
            exc.message,
            code=code,
            retryable=code in {FetchErrorCode.RATE_LIMITED, FetchErrorCode.SOURCE_UNAVAILABLE},
            http_status=status_by_code.get(code, 422),
            details={"url": url} if url else None,
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


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Parse a bounded Retry-After value without persisting its raw header."""

    raw_value = str(response.headers.get("Retry-After", "")).strip()
    if not raw_value:
        return None
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


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
            retry_after_seconds=_retry_after_seconds(response),
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
            "Stealth browser fallback failed for %s (%s)",
            redacted_url(url),
            type(exc).__name__,
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


@dataclass(frozen=True)
class SourceAdapterRegistration:
    adapter_id: str
    label: str
    domains: tuple[str, ...]
    adapter_version: str


class SourceAdapterRegistry:
    def __init__(self, adapters: Iterable[GenericHtmlSourceAdapter] | None = None):
        self.adapters = list(adapters or [GenericHtmlSourceAdapter()])
        registrations: list[SourceAdapterRegistration] = []
        adapter_ids: set[str] = set()
        domain_owners: dict[str, str] = {}

        for adapter in self.adapters:
            domains = tuple(str(domain).strip().casefold() for domain in getattr(adapter, "domains", ()) if domain)
            if not domains:
                continue
            adapter_id = str(getattr(adapter, "adapter_id", "")).strip()
            label = str(getattr(adapter, "label", "")).strip()
            adapter_version = str(getattr(adapter, "adapter_version", "")).strip()
            if not adapter_id or not label or not adapter_version:
                raise ValueError("Registered source adapters require id, label, domains, and version metadata")
            if adapter_id in adapter_ids:
                raise ValueError(f"Duplicate source adapter id: {adapter_id}")
            adapter_ids.add(adapter_id)
            for domain in domains:
                owner = domain_owners.get(domain)
                if owner is not None:
                    raise ValueError(f"Duplicate source adapter domain: {domain} ({owner}, {adapter_id})")
                domain_owners[domain] = adapter_id
            registrations.append(
                SourceAdapterRegistration(
                    adapter_id=adapter_id,
                    label=label,
                    domains=domains,
                    adapter_version=adapter_version,
                )
            )

        self.registrations = tuple(registrations)

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
    legacy_69shuba = SelectorSourceAdapter(
        adapter_id="69shuba",
        label="69shuba",
        domains=("69shuba.com", "69shuba.cx", "69shux.com"),
        title_patterns=(r"<h1[^>]*>(.*?)</h1>", r'<meta property="og:title" content="([^"]+)"'),
        author_patterns=(r"(?:作者|作\s*者)\s*[:：]\s*([^<\n\r]{1,40})",),
        description_patterns=(
            r'<meta name="description" content="([^"]+)"',
            r'<div[^>]+class="[^"]*intro[^"]*"[^>]*>(.*?)</div>',
        ),
        cover_patterns=(
            r'<meta property="og:image" content="([^"]+)"',
            r'<img[^>]+src="([^"]+)"[^>]+(?:cover|bookimg|fmimg)',
        ),
        chapter_link_patterns=(chapter_link_pattern,),
        content_patterns=(
            r'<div[^>]+class="container"[^>]*>(.*?)</div>\s*<div[^>]+class="(?:bottom|foot|pagefoot)',
            r'<div[^>]+class="[^"]*txtnav[^"]*"[^>]*>(.*?)</div>\s*<div',
            r'<div[^>]+id="content"[^>]*>(.*?)</div>',
            r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        ),
    )
    legacy_69shumi = SelectorSourceAdapter(
        adapter_id="69shumi",
        label="69shumi",
        domains=("69shumi.net", "69shumi.com"),
        title_patterns=(
            r'<h1[^>]+class="[^"]*bookTitle[^"]*"[^>]*>(.*?)</h1>',
            r"<h1[^>]*>(.*?)</h1>",
        ),
        author_patterns=(r'<p[^>]+class="[^"]*booktag[^"]*"[^>]*>(.*?)</p>',),
        description_patterns=(r'<p[^>]+id="bookIntro"[^>]*>(.*?)</p>',),
        cover_patterns=(r'<div[^>]+class="[^"]*col-sm-2[^"]*"[^>]*>\s*<img[^>]+src="([^"]+)"',),
        chapter_link_patterns=(r'<dd[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)',),
        content_patterns=(r'<div[^>]+id="booktxt"[^>]*>(.*?)</div>', r'<div[^>]+id="content"[^>]*>(.*?)</div>'),
    )
    remove_selectors = (
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        ".advertisement",
        ".ads",
        ".ad",
        ".breadcrumb",
        ".popup",
        ".bottom",
        ".foot",
        ".pagefoot",
    )
    registered_adapters: list[GenericHtmlSourceAdapter] = [
        DomSourceAdapter(
            adapter_id="69shuba",
            label="69shuba",
            domains=("69shuba.com", "69shuba.cx", "69shux.com"),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                    DomSelector("title"),
                ),
                chapter_title=(
                    DomSelector("h1.chapter-title"),
                    DomSelector("h1"),
                    DomSelector("title"),
                ),
                author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
                description=(
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector('meta[property="og:image"]', "content"),
                    DomSelector("img.cover", "src"),
                    DomSelector(".bookimg img", "src"),
                    DomSelector(".fmimg img", "src"),
                ),
                chapter_links=(
                    DomSelector("#list a", "href"),
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#content"),
                    DomSelector(".txtnav"),
                    DomSelector(".chapter-content"),
                ),
                remove_selectors=remove_selectors,
            ),
            adapter_version="69shuba-dom-v1",
            regex_fallback=legacy_69shuba,
        ),
        DomSourceAdapter(
            adapter_id="69shumi",
            label="69shumi",
            domains=("69shumi.net", "69shumi.com"),
            selectors=DomSelectorConfig(
                title=(DomSelector("h1.bookTitle"), DomSelector("h1"), DomSelector("title")),
                chapter_title=(DomSelector("h1.chapter-title"), DomSelector("h1"), DomSelector("title")),
                author=(DomSelector(".booktag"), DomSelector('meta[name="author"]', "content")),
                description=(
                    DomSelector("#bookIntro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".col-sm-2 img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(DomSelector("dd a", "href"), DomSelector(".chapter-list a", "href")),
                chapter_content=(DomSelector("#booktxt"), DomSelector("#content")),
                remove_selectors=remove_selectors,
            ),
            adapter_version="69shumi-dom-v1",
            regex_fallback=legacy_69shumi,
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

        # ── P14: New sources ported from Excerpo ──────────────────────────────
        DomSourceAdapter(
            adapter_id="royalroad",
            label="Royal Road",
            domains=("royalroad.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector('h1[property="name"]'),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                    DomSelector("title"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector('a[property="author"]'),
                    DomSelector(".profile-name a"),
                    DomSelector("h4 a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".fiction-description"),
                    DomSelector(".description"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector(".thumbnail.inline-block", "src"),
                    DomSelector(".fiction-cover img", "src"),
                    DomSelector('meta[property="og:image"]', "content"),
                ),
                chapter_links=(
                    DomSelector("tr.chapter-row a[href*='/chapter/']", "href"),
                    DomSelector("a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector("div.chapter-inner.chapter-content"),
                    DomSelector(".chapter-content"),
                ),
            ),
            adapter_version="royalroad-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="scribblehub",
            label="Scribble Hub",
            domains=("scribblehub.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector('div.fic_title[property="name"]'),
                    DomSelector(".fic_title"),
                    DomSelector('meta[property="og:title"]', "content"),
                    DomSelector("title"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector('div.auth_name[property="name"]'),
                    DomSelector(".auth_name a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector('div.wi_fic_desc[property="description"]'),
                    DomSelector(".wi_fic_desc"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector('div.novel-cover img[property="image"]', "src"),
                    DomSelector("img.thumbnail.inline-block", "src"),
                    DomSelector('meta[property="og:image"]', "content"),
                ),
                chapter_links=(
                    DomSelector(".catalog a", "href"),
                    DomSelector("a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector(".chp_raw"),
                    DomSelector(".chapter-content"),
                ),
            ),
            adapter_version="scribblehub-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="ao3",
            label="Archive of Our Own",
            domains=("archiveofourown.org",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h2.title.heading"),
                    DomSelector('meta[property="og:title"]', "content"),
                    DomSelector("title"),
                ),
                chapter_title=(DomSelector("h2.title"), DomSelector("h3.title"), DomSelector("title")),
                author=(
                    DomSelector('h3.byline.heading a[rel="author"]'),
                    DomSelector(".byline a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("div.summary.module blockquote"),
                    DomSelector("div.summary.module"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector('meta[property="og:image"]', "content"),),
                chapter_links=(
                    DomSelector("li.chapter a[href*='/works/'][href*='/chapters/']", "href"),
                    DomSelector("a[href*='/chapters/']", "href"),
                ),
                chapter_content=(
                    DomSelector("div.userstuff.module"),
                    DomSelector(".userstuff"),
                ),
            ),
            adapter_version="ao3-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="lnmtl",
            label="LNMTL",
            domains=("lnmtl.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".novel-name"),
                    DomSelector(".novel-title h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".chapter-title"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".novel-author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".novel-description"),
                    DomSelector(".description"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector(".novel-cover img", "src"),
                    DomSelector('meta[property="og:image"]', "content"),
                ),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector(".chapter-body"),
                    DomSelector(".translated-chapter"),
                    DomSelector("#chapter-content"),
                ),
            ),
            adapter_version="lnmtl-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="foxaholic",
            label="Foxaholic",
            domains=("foxaholic.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector(".post-title h3"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector(".author-content"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector(".summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector(".summary_image img", "src"),
                    DomSelector('meta[property="og:image"]', "content"),
                ),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(
                    DomSelector(".reading-content"),
                    DomSelector(".text-left"),
                    DomSelector(".entry-content"),
                ),
            ),
            adapter_version="foxaholic-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="shubaow",
            label="Shubaow",
            domains=("shubaow.org",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("div.info h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".info .fix p"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".desc"),
                    DomSelector(".xdesc"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".imgbox img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#section-list li a", "href"),
                    DomSelector(".chapter-list a", "href"),
                ),
                chapter_content=(DomSelector(".content"), DomSelector("#content")),
            ),
            adapter_version="shubaow-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="wbnovel",
            label="WBNovel",
            domains=("wbnovel.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".rate-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".summary__content"),
                    DomSelector(".post-content"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(DomSelector("div.text-left"), DomSelector(".reading-content")),
            ),
            adapter_version="wbnovel-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="kakuyomu",
            label="Kakuyomu",
            domains=("kakuyomu.jp",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("#workTitle"),
                    DomSelector(".work-title"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".chapter-title"), DomSelector(".widget-episodeTitle"), DomSelector("title")),
                author=(
                    DomSelector(".author-name"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#introduction"),
                    DomSelector(".introduction"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector('meta[property="og:image"]', "content"),),
                chapter_links=(
                    DomSelector(".widget-toc-items a", "href"),
                    DomSelector(".episodeList a", "href"),
                ),
                chapter_content=(
                    DomSelector(".widget-episodeBody"),
                    DomSelector(".scene"),
                ),
            ),
            adapter_version="kakuyomu-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="syosetu",
            label="Syosetu",
            domains=("syosetu.com", "ncode.syosetu.com", "novel18.syosetu.com"),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".p-novel__title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".p-novel__title"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".p-novel__author a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#novel_ex"),
                    DomSelector(".p-novel__ex"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector('meta[property="og:image"]', "content"),),
                chapter_links=(
                    DomSelector(".p-eplist a", "href"),
                    DomSelector(".index_box a", "href"),
                    DomSelector("a[href*='/n']", "href"),
                ),
                chapter_content=(
                    DomSelector(".p-novel__text"),
                    DomSelector("#novel_honbun"),
                    DomSelector(".novel_view"),
                ),
            ),
            adapter_version="syosetu-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="meionovel",
            label="Meionovel",
            domains=("meionovel.id", "meionovels.com"),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector(".post-title h3"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector(".summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(
                    DomSelector(".reading-content"),
                    DomSelector(".text-left"),
                ),
            ),
            adapter_version="meionovel-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="centralnovel",
            label="Central Novel",
            domains=("centralnovel.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector(".post-title h3"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector(".summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(
                    DomSelector(".reading-content"),
                    DomSelector(".text-left"),
                ),
            ),
            adapter_version="centralnovel-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="ranobelib",
            label="RanobeLib",
            domains=("ranobelib.me",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".book-name"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".chapter-title"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".book-author a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".book-description"),
                    DomSelector(".description"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(
                    DomSelector(".book-cover img", "src"),
                    DomSelector('meta[property="og:image"]', "content"),
                ),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector(".menu a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector(".chapter-content"),
                    DomSelector(".reader-text"),
                    DomSelector("#content"),
                ),
            ),
            adapter_version="ranobelib-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="syosetu_org",
            label="Syosetu.org",
            domains=("syosetu.org",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("#title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector("#author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#ex"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector('meta[property="og:image"]', "content"),),
                chapter_links=(
                    DomSelector(".menu a", "href"),
                    DomSelector("a[href*='/novel/']", "href"),
                ),
                chapter_content=(
                    DomSelector("#novel"),
                    DomSelector(".novel_view"),
                ),
            ),
            adapter_version="syosetu_org-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="novelgo",
            label="NovelGo",
            domains=("novelgo.id",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".summary__content"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(DomSelector(".reading-content"), DomSelector(".text-left")),
            ),
            adapter_version="novelgo-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="novellunar",
            label="NovelLunar",
            domains=("novellunar.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(DomSelector(".reading-content"), DomSelector(".text-left")),
            ),
            adapter_version="novellunar-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="phoenixnovels",
            label="Phoenix Novels",
            domains=("phoenixnovels.com.br",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(DomSelector(".reading-content"), DomSelector(".text-left")),
            ),
            adapter_version="phoenixnovels-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="chireads",
            label="Chireads",
            domains=("chireads.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".summary__content"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector("li.wp-manga-chapter a", "href"),
                ),
                chapter_content=(DomSelector(".reading-content"), DomSelector(".text-left")),
            ),
            adapter_version="chireads-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="fenrirscans",
            label="Fenrir Scans",
            domains=("fenrirscans.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".post-title h1"),
                    DomSelector(".post-title h3"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector(".post-title h1"), DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".author-content a"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".description-summary"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".summary_image img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".wp-manga-chapter a", "href"),
                    DomSelector(".listing-chapters a", "href"),
                ),
                chapter_content=(DomSelector(".reading-content"), DomSelector(".text-left")),
            ),
            adapter_version="fenrirscans-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="pixiv",
            label="Pixiv",
            domains=("pixiv.net",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector('h1[class*="title"]'),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector('a[data-gtm-user-id]'),
                    DomSelector(".author-name"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector('meta[property="og:description"]', "content"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector('meta[property="og:image"]', "content"),),
                chapter_links=(
                    DomSelector('a[href*="/novel/series/"]', "href"),
                    DomSelector('a[href*="/novel/"]', "href"),
                ),
                chapter_content=(
                    DomSelector('[class*="content"]'),
                    DomSelector("pre"),
                ),
            ),
            adapter_version="pixiv-dom-v1",
        ),

        DomSourceAdapter(
            adapter_id="23qb",
            label="23qb",
            domains=("23qb.net",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.bookTitle"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".booktag"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#bookIntro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".col-sm-2 img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#newlist dd a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#booktxt"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="23qb-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="ihuaben",
            label="ihuaben",
            domains=("ihuaben.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".book-info .author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".book-intro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".book-img img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("#chapterList a", "href"),
                    DomSelector("a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector(".chapter-content"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="ihuaben-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="shuhaige",
            label="shuhaige",
            domains=("shuhaige.net",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1"),
                    DomSelector("#info h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector("#info p"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#intro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector("#fmimg img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#list dd a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#content"),
                    DomSelector("#booktxt"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="shuhaige-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="sto55",
            label="sto55",
            domains=("sto55.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".book-info .author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".book-intro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".book-img img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("#list a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#content"),
                    DomSelector(".content"),
                    DomSelector("#booktxt"),
                ),
            ),
            adapter_version="sto55-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="sto9",
            label="sto9",
            domains=("sto9.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".booktag"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#bookIntro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".col-sm-2 img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#newlist dd a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#booktxt"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="sto9-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="ttkan",
            label="ttkan",
            domains=("ttkan.co",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".book-info .author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".book-intro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".book-img img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("#chapter-list a", "href"),
                    DomSelector("a[href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector("#content"),
                    DomSelector(".content"),
                    DomSelector(".chapter-content"),
                ),
            ),
            adapter_version="ttkan-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="twkan",
            label="twkan",
            domains=("twkan.com",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("h1.book-title"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".booktag"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#bookIntro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".col-sm-2 img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#newlist dd a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#booktxt"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="twkan-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="xbiquge",
            label="xbiquge",
            domains=("xbiquge.bz", "xbiquge.co", "xbiquge.info", "xbiquge.so", "xbiquge.la", "xbiquge.me"),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector("#info h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector("#info p"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector("#intro"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector("#fmimg img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector("#list dd a", "href"),
                    DomSelector("dd a", "href"),
                ),
                chapter_content=(
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="xbiquge-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="powanjuan",
            label="powanjuan",
            domains=("powanjuan.cc",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".desc h1"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".descTip span"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".desc .content"),
                    DomSelector(".intro"),
                    DomSelector('meta[name="description"]', "content"),
                ),
                cover=(DomSelector(".desc img", "src"), DomSelector(".book img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".catalog ul.clearfix li a", "href"),
                    DomSelector(".chapter-list a", "href"),
                ),
                chapter_content=(
                    DomSelector("#mycontent"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="powanjuan-dom-v1",
        ),
        DomSourceAdapter(
            adapter_id="po18",
            label="PO18",
            domains=("po18.tw",),
            selectors=DomSelectorConfig(
                title=(
                    DomSelector(".book-name"),
                    DomSelector("h1"),
                    DomSelector('meta[property="og:title"]', "content"),
                ),
                chapter_title=(DomSelector("h1"), DomSelector("title")),
                author=(
                    DomSelector(".book-author"),
                    DomSelector('meta[name="author"]', "content"),
                ),
                description=(
                    DomSelector(".book-description"),
                    DomSelector(".intro"),
                    DomSelector('meta[property="og:description"]', "content"),
                ),
                cover=(DomSelector(".book-cover img", "src"), DomSelector('meta[property="og:image"]', "content")),
                chapter_links=(
                    DomSelector(".chapter-list a", "href"),
                    DomSelector("a[href*='/books/'][href*='/chapter/']", "href"),
                ),
                chapter_content=(
                    DomSelector(".book-content"),
                    DomSelector("#content"),
                    DomSelector(".content"),
                ),
            ),
            adapter_version="po18-dom-v1",
        ),

        # ── End P14 new sources ─────────────────────────────────────────────────

        GenericHtmlSourceAdapter(),
    ]

    # Selector configurations below were the pre-P12 registry implementation.
    # P13 keeps their adapter identity/domain declarations while replacing their
    # runtime extraction path with explicit versioned DOM selector configs. They
    # are not used as regex fallbacks.
    dom_selector_configs: dict[str, DomSelectorConfig] = {
        "biquge": DomSelectorConfig(
            title=(DomSelector("h1.book-title"), DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector('meta[property="og:image"]', "content"), DomSelector("img.cover", "src")),
            chapter_links=(DomSelector("#list a", "href"), DomSelector(".chapter-list a", "href"), DomSelector("dd a", "href")),
            chapter_content=(DomSelector("#chaptercontent"), DomSelector("#content"), DomSelector(".read-content")),
            remove_selectors=remove_selectors,
        ),
        "uukanshu": DomSelectorConfig(
            title=(DomSelector("h1.booktitle"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector('meta[property="og:image"]', "content"), DomSelector("img.cover", "src")),
            chapter_links=(DomSelector("#list a", "href"), DomSelector(".chapter-list a", "href"), DomSelector("dd a", "href")),
            chapter_content=(DomSelector("#contentbox"), DomSelector("#content")),
            remove_selectors=remove_selectors,
        ),
        "17k": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".name"), DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector("img.cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("#list a", "href"), DomSelector("a[data-bid]", "href")),
            chapter_content=(DomSelector(".readAreaBox.content"), DomSelector(".readAreaBox"), DomSelector(".content")),
            remove_selectors=remove_selectors,
        ),
        "52shuku": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".info"), DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector("img.cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("li a", "href")),
            chapter_content=(DomSelector("article.content"), DomSelector(".content")),
            remove_selectors=remove_selectors,
        ),
        "fanqienovel": DomSelectorConfig(
            title=(DomSelector('meta[property="og:novel:book_name"]', "content"), DomSelector('meta[property="og:title"]', "content"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector('meta[property="og:novel:author"]', "content"), DomSelector(".info-author"), DomSelector(".author")),
            description=(DomSelector('meta[name="description"]', "content"), DomSelector(".intro")),
            cover=(DomSelector('meta[property="og:image"]', "content"), DomSelector("img.cover", "src")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("a.chapter-link", "href")),
            chapter_content=(DomSelector(".muye-reader-content"), DomSelector(".reader-content")),
            remove_selectors=remove_selectors,
        ),
        "jjwxc": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector("a.oneauthor"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector('meta[name="description"]', "content"), DomSelector(".intro")),
            cover=(DomSelector("img.cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("a.chapter-link", "href")),
            chapter_content=(DomSelector(".noveltext"), DomSelector(".read-content")),
            remove_selectors=remove_selectors,
        ),
        "qidian": DomSelectorConfig(
            title=(DomSelector('meta[property="og:novel:book_name"]', "content"), DomSelector('meta[property="og:title"]', "content"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector('meta[property="og:novel:author"]', "content"), DomSelector(".author")),
            description=(DomSelector('meta[name="description"]', "content"), DomSelector(".intro")),
            cover=(DomSelector('meta[property="og:image"]', "content"), DomSelector("img.cover", "src")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("a.chapter-link", "href"), DomSelector("a[data-bid]", "href")),
            chapter_content=(DomSelector(".read-content"), DomSelector(".j_readContent")),
            remove_selectors=remove_selectors,
        ),
        "novel543": DomSelectorConfig(
            title=(DomSelector("h1.title"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector(".cover img", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("li a", "href")),
            chapter_content=(DomSelector(".content"),),
            remove_selectors=remove_selectors,
        ),
        "hetushu": DomSelectorConfig(
            title=(DomSelector("h2"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1"), DomSelector("h2")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector("img.cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector("#list a", "href"), DomSelector(".chapter-list a", "href")),
            chapter_content=(DomSelector("#content"),),
            remove_selectors=remove_selectors,
        ),
        "ixdzs8": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".bauthor"), DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector("#intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector("img.cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("#list a", "href")),
            chapter_content=(DomSelector(".content"), DomSelector("#content")),
            remove_selectors=remove_selectors,
        ),
        "xbanxia": DomSelectorConfig(
            title=(DomSelector(".book-describe h1"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".describe-html"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector(".book-img img", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("li a", "href")),
            chapter_content=(DomSelector("#content"), DomSelector(".content")),
            remove_selectors=remove_selectors,
        ),
        "bookqq": DomSelectorConfig(
            title=(DomSelector("h1.book-title"), DomSelector("h1"), DomSelector("title")),
            chapter_title=(DomSelector(".chapter-title"), DomSelector("h1")),
            author=(DomSelector(".author"), DomSelector('meta[name="author"]', "content")),
            description=(DomSelector(".book-intro"), DomSelector('meta[name="description"]', "content")),
            cover=(DomSelector("img.book-cover", "src"), DomSelector('meta[property="og:image"]', "content")),
            chapter_links=(DomSelector(".chapter-list a", "href"), DomSelector("a.chapter-link", "href")),
            chapter_content=(DomSelector(".read-content"),),
            remove_selectors=remove_selectors,
        ),
        "69shuba": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector("h1"), DomSelector(".chapter-title")),
            author=(DomSelector('meta[name="author"]', "content"), DomSelector(".author")),
            description=(DomSelector('meta[name="description"]', "content"),),
            cover=(DomSelector('meta[property="og:image"]', "content"),),
            chapter_links=(
                DomSelector("li[data-num] a", "href"),
                DomSelector(".muluh1 + ul li a", "href"),
                DomSelector("ul li a[href*='/txt/']", "href"),
            ),
            chapter_content=(
                DomSelector(".txtnav"),
                DomSelector("#content"),
                DomSelector("#chaptercontent"),
                DomSelector(".read-content"),
            ),
            remove_selectors=remove_selectors,
        ),
        "69shumi": DomSelectorConfig(
            title=(DomSelector("h1"), DomSelector('meta[property="og:title"]', "content"), DomSelector("title")),
            chapter_title=(DomSelector("h1"), DomSelector(".chapter-title")),
            author=(DomSelector('meta[name="author"]', "content"), DomSelector(".author")),
            description=(DomSelector('meta[name="description"]', "content"),),
            cover=(DomSelector('meta[property="og:image"]', "content"),),
            chapter_links=(
                DomSelector("li[data-num] a", "href"),
                DomSelector("ul li a[href*='/txt/']", "href"),
            ),
            chapter_content=(DomSelector("#content"), DomSelector("#chaptercontent"), DomSelector(".read-content")),
            remove_selectors=remove_selectors,
        ),
    }

    return [
        DomSourceAdapter(
            adapter_id=adapter.adapter_id,
            label=adapter.label,
            domains=adapter.domains,
            selectors=dom_selector_configs[adapter.adapter_id],
            adapter_version=f"{adapter.adapter_id}-dom-v1",
        )
        if isinstance(adapter, SelectorSourceAdapter)
        else adapter
        for adapter in registered_adapters
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
    adapters = [adapter for adapter in _DEFAULT_REGISTRY.adapters if _adapter_domains(adapter)]
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
