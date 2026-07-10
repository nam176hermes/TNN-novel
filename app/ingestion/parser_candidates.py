from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests

from app.ingestion.source_health import (
    HEALTH_MAX_READ_BYTES,
    HEALTH_TIMEOUT_SECONDS,
    validate_source_health_url,
)

PARSER_CANDIDATE_USER_AGENT = "Novel-TNN ParserCandidate/1.0"
RequestGet = Callable[..., requests.Response]

_CHAPTER_TEXT_RE = re.compile(
    r"(?i)(chapter|chap\.|ch\.|episode|ep\.|第\s*[\w一二三四五六七八九十百千万零〇两]+[章节回卷集部])"
)
_NEXT_TEXT_RE = re.compile(r"(?i)\bnext\b|next chapter|下一章|下章|下一页|下一篇")
_CONTENT_ATTR_RE = re.compile(r"(?i)(content|chapter|article|read|entry|booktext|novel)")


@dataclass
class _ContentCandidate:
    selector: str
    text_parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self.text_parts))


class _PreviewParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.anchors: list[dict[str, str]] = []
        self.content_candidates: list[_ContentCandidate] = []
        self._text_stack: list[str] = []
        self._anchor_href: str = ""
        self._anchor_parts: list[str] = []
        self._active_content_stack: list[int] = []
        self._element_content_stack: list[int | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.casefold(): value or "" for name, value in attrs}
        lowered_tag = tag.casefold()
        if lowered_tag in {"title", "h1"}:
            self._text_stack.append(lowered_tag)
        if lowered_tag == "a":
            self._anchor_href = attr_map.get("href", "")
            self._anchor_parts = []

        selector = _content_selector(lowered_tag, attr_map)
        if selector:
            self.content_candidates.append(_ContentCandidate(selector=selector))
            candidate_index = len(self.content_candidates) - 1
            self._active_content_stack.append(candidate_index)
            self._element_content_stack.append(candidate_index)
        else:
            self._element_content_stack.append(None)

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.casefold()
        if self._text_stack and self._text_stack[-1] == lowered_tag:
            self._text_stack.pop()
        if lowered_tag == "a" and self._anchor_href:
            text = _clean_text(" ".join(self._anchor_parts))
            if text:
                self.anchors.append(
                    {
                        "title": text[:160],
                        "url": urljoin(self.base_url, self._anchor_href),
                    }
                )
            self._anchor_href = ""
            self._anchor_parts = []
        if self._element_content_stack:
            candidate_index = self._element_content_stack.pop()
            if candidate_index is not None and self._active_content_stack and self._active_content_stack[-1] == candidate_index:
                self._active_content_stack.pop()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._text_stack:
            if self._text_stack[-1] == "title":
                self.title_parts.append(text)
            elif self._text_stack[-1] == "h1":
                self.h1_parts.append(text)
        if self._anchor_href:
            self._anchor_parts.append(text)
        for candidate_index in self._active_content_stack:
            self.content_candidates[candidate_index].text_parts.append(text)


def _utcnow_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _content_selector(tag: str, attrs: dict[str, str]) -> str:
    attr_text = " ".join(value for value in (attrs.get("id", ""), attrs.get("class", "")) if value)
    if tag in {"article", "main"}:
        return tag
    if attr_text and _CONTENT_ATTR_RE.search(attr_text):
        name = attrs.get("id") or attrs.get("class", "")
        marker = "#" if attrs.get("id") else "."
        normalized = re.sub(r"\s+", ".", name.strip())
        return f"{tag}{marker}{normalized}"[:120]
    return ""


def _read_limited_body(response: requests.Response) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        remaining = HEALTH_MAX_READ_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= HEALTH_MAX_READ_BYTES:
            break
    return b"".join(chunks).decode("utf-8", errors="ignore")


def _candidate_payload(
    entry: dict[str, Any],
    *,
    sample_url: str,
    detected_title: str = "",
    detected_chapter_list: list[dict[str, Any]] | None = None,
    parser_confidence: str = "low",
    failure_reason: str = "",
    status: str = "needs_review",
) -> dict[str, Any]:
    now = _utcnow_text()
    domain = str(entry.get("domain") or urlparse(sample_url).hostname or "").strip()
    return {
        "catalog_entry_id": str(entry.get("id") or ""),
        "domain": domain,
        "sample_url": sample_url,
        "detected_title": detected_title,
        "detected_chapter_list": detected_chapter_list or [],
        "parser_confidence": parser_confidence,
        "failure_reason": failure_reason,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": "",
        "reviewed_by": "",
    }


def _failed_candidate(entry: dict[str, Any], *, sample_url: str, reason: str) -> dict[str, Any]:
    return _candidate_payload(
        entry,
        sample_url=sample_url,
        parser_confidence="failed",
        failure_reason=reason,
        status="draft",
    )


def _detect_candidate(entry: dict[str, Any], safe_url: str, html: str) -> dict[str, Any]:
    parser = _PreviewParser(safe_url)
    parser.feed(html)

    h1_title = _clean_text(" ".join(parser.h1_parts))
    page_title = _clean_text(" ".join(parser.title_parts))
    detected_title = h1_title or re.split(r"\s+[-|_·]\s+", page_title, maxsplit=1)[0] or str(entry.get("name") or "")

    chapter_links: list[dict[str, Any]] = []
    next_links: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for anchor in parser.anchors:
        title = anchor.get("title", "")
        url = anchor.get("url", "")
        if not url or url in seen_urls:
            continue
        if _NEXT_TEXT_RE.search(title):
            next_links.append({"kind": "next_chapter", "title": title, "url": url})
        if _CHAPTER_TEXT_RE.search(title) or re.search(r"/(?:chapter|chap|read|book)/", url, re.I):
            chapter_links.append({"kind": "chapter", "title": title, "url": url})
            seen_urls.add(url)
        if len(chapter_links) >= 20:
            break

    content_candidates: list[dict[str, Any]] = []
    for candidate in parser.content_candidates[:5]:
        text_len = len(candidate.text)
        if text_len < 32:
            continue
        content_candidates.append(
            {
                "kind": "content_container",
                "selector": candidate.selector,
                "text_length": text_len,
            }
        )

    signals = [*chapter_links[:20], *next_links[:3], *content_candidates]
    has_title = bool(_clean_text(detected_title))
    has_chapters = len(chapter_links) >= 2
    has_content = bool(content_candidates)
    if has_title and has_chapters and has_content:
        confidence = "high"
    elif (has_title and chapter_links) or (has_chapters and has_content):
        confidence = "medium"
    else:
        confidence = "low"

    return _candidate_payload(
        entry,
        sample_url=safe_url,
        detected_title=_clean_text(detected_title)[:255],
        detected_chapter_list=signals,
        parser_confidence=confidence,
        failure_reason="",
        status="needs_review",
    )


def create_parser_candidate(
    entry: dict[str, Any],
    *,
    sample_url: str = "",
    request_get: RequestGet = requests.get,
) -> dict[str, Any]:
    """Create a one-page parser candidate preview without supporting the source."""
    requested_url = str(sample_url or entry.get("url") or "").strip()
    safe_url, blocked_reason = validate_source_health_url(requested_url)
    if blocked_reason:
        return _failed_candidate(entry, sample_url=requested_url, reason=blocked_reason)

    headers = {
        "User-Agent": PARSER_CANDIDATE_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
    }
    try:
        response = request_get(
            safe_url,
            headers=headers,
            timeout=HEALTH_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout:
        return _failed_candidate(entry, sample_url=safe_url, reason="request_timeout")
    except requests.RequestException:
        return _failed_candidate(entry, sample_url=safe_url, reason="request_failed")

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code >= 400:
        return _failed_candidate(entry, sample_url=safe_url, reason=f"http_{status_code}")

    html = _read_limited_body(response)
    if not html.strip():
        return _failed_candidate(entry, sample_url=safe_url, reason="empty_preview")
    if re.search(r"captcha|cloudflare|access denied|forbidden|verify you are human", html, re.I):
        return _failed_candidate(entry, sample_url=safe_url, reason="captcha_or_blocked")

    return _detect_candidate(entry, safe_url, html)
