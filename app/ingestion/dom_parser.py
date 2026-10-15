from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import Callable, Iterable
from urllib.parse import urljoin

from app.ingestion.chapter_cleaner import clean_chapter
from app.ingestion.text_normalization import normalize_import_text, source_hash


@dataclass(frozen=True)
class DomSelector:
    """A small, ordered CSS-selector subset used by source configurations."""

    query: str
    attribute: str = ""


@dataclass(frozen=True)
class DomSelectorConfig:
    title: tuple[DomSelector, ...]
    chapter_title: tuple[DomSelector, ...] = ()
    author: tuple[DomSelector, ...] = ()
    description: tuple[DomSelector, ...] = ()
    cover: tuple[DomSelector, ...] = ()
    chapter_links: tuple[DomSelector, ...] = ()
    chapter_content: tuple[DomSelector, ...] = ()
    remove_selectors: tuple[str, ...] = (
        "script",
        "style",
        "noscript",
        "nav",
        ".advertisement",
        ".ads",
        ".ad",
        ".breadcrumb",
        ".popup",
    )


@dataclass(frozen=True)
class DomPreviewData:
    title: str
    author: str
    description: str
    cover_url: str
    chapter_links: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DomChapterData:
    title: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class DomParserError(ValueError):
    message: str
    code: str
    fallback_allowed: bool = False

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


@dataclass
class DomNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[DomNode | str] = field(default_factory=list)
    parent: DomNode | None = field(default=None, repr=False)


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _DomTreeBuilder(HTMLParser):
    MAX_DEPTH = 256
    MAX_NODES = 100_000

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = DomNode("document")
        self._stack = [self.root]
        self._node_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._node_count += 1
        if self._node_count > self.MAX_NODES or len(self._stack) > self.MAX_DEPTH:
            raise ValueError("HTML document exceeds DOM limits")
        node = DomNode(
            tag.casefold(),
            {name.casefold(): value or "" for name, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        wanted = tag.casefold()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == wanted:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


_SELECTOR_TOKEN_RE = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*)?"
    r"(?P<id>#[\w-]+)?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)$"
)
_ATTR_RE = re.compile(r"\[([\w:-]+)(?:\s*=\s*(['\"]?)(.*?)\2)?\]")


def _iter_nodes(node: DomNode) -> Iterable[DomNode]:
    stack = [child for child in reversed(node.children) if isinstance(child, DomNode)]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(child for child in reversed(current.children) if isinstance(child, DomNode))


def _matches_token(node: DomNode, token: str) -> bool:
    match = _SELECTOR_TOKEN_RE.fullmatch(token)
    if not match:
        return False
    if match.group("tag") and node.tag != match.group("tag").casefold():
        return False
    wanted_id = (match.group("id") or "").removeprefix("#")
    if wanted_id and node.attrs.get("id", "") != wanted_id:
        return False
    wanted_classes = {part for part in (match.group("classes") or "").split(".") if part}
    actual_classes = set(node.attrs.get("class", "").split())
    if not wanted_classes.issubset(actual_classes):
        return False
    for attr_match in _ATTR_RE.finditer(match.group("attrs") or ""):
        name, _quote, value = attr_match.groups()
        if name.casefold() not in node.attrs:
            return False
        if value and node.attrs.get(name.casefold()) != value:
            return False
    return True


def _matches_selector(node: DomNode, selector: str) -> bool:
    tokens = tuple(part for part in selector.strip().split() if part)
    if not tokens or not _matches_token(node, tokens[-1]):
        return False
    ancestor = node.parent
    for token in reversed(tokens[:-1]):
        while ancestor is not None and not _matches_token(ancestor, token):
            ancestor = ancestor.parent
        if ancestor is None:
            return False
        ancestor = ancestor.parent
    return True


class DomDocument:
    def __init__(self, html: str) -> None:
        builder = _DomTreeBuilder()
        try:
            builder.feed(html)
            builder.close()
        except (AssertionError, ValueError) as exc:
            raise DomParserError("HTML document could not be parsed", "parse_failed") from exc
        self.root = builder.root
        self._removed: set[int] = set()

    def select_all(self, selector: str, *, include_removed: bool = False) -> list[DomNode]:
        return [
            node
            for node in _iter_nodes(self.root)
            if (include_removed or not self.is_removed(node)) and _matches_selector(node, selector)
        ]

    def select_one(self, selector: str) -> DomNode | None:
        matches = self.select_all(selector)
        return matches[0] if matches else None

    def remove(self, selectors: Iterable[str]) -> None:
        for selector in selectors:
            for node in self.select_all(selector, include_removed=True):
                self._removed.add(id(node))

    def is_removed(self, node: DomNode) -> bool:
        current: DomNode | None = node
        while current is not None:
            if id(current) in self._removed:
                return True
            current = current.parent
        return False

    def text_content(self, node: DomNode) -> str:
        chunks: list[str] = []

        def visit(current: DomNode) -> None:
            if self.is_removed(current):
                return
            for child in current.children:
                if isinstance(child, str):
                    chunks.append(child)
                elif child.tag == "br":
                    chunks.append("\n")
                else:
                    visit(child)

        visit(node)
        return _normalize_inline("".join(chunks))

    def paragraph_text(self, node: DomNode) -> str:
        chunks: list[str] = []
        block_tags = {
            "address",
            "article",
            "blockquote",
            "dd",
            "div",
            "dl",
            "dt",
            "figcaption",
            "figure",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "main",
            "p",
            "section",
            "td",
            "th",
            "tr",
        }

        def visit(current: DomNode) -> None:
            if self.is_removed(current):
                return
            is_block = current.tag in block_tags
            if is_block:
                chunks.append("\n")
            for child in current.children:
                if isinstance(child, str):
                    chunks.append(child)
                elif child.tag == "br":
                    chunks.append("\n")
                else:
                    visit(child)
            if is_block:
                chunks.append("\n")

        visit(node)
        return _normalize_paragraphs("".join(chunks))


_CHALLENGE_PATTERNS = (
    re.compile(r"challenge-platform", re.I),
    re.compile(r"cf-turnstile|g-recaptcha|data-sitekey", re.I),
    re.compile(r"just a moment|checking your browser", re.I),
    re.compile(r"cloudflare[^<]{0,80}(?:challenge|verification)", re.I),
    re.compile(r"(?:验证码|安全验证|人机验证|访问过于频繁)", re.I),
)
_RATE_LIMIT_PATTERNS = (
    re.compile(r"<title[^>]*>[^<]*(?:429|too many requests|rate limit)", re.I),
    re.compile(r"(?:too many requests|rate limit exceeded|请求过于频繁)", re.I),
)
_SOURCE_ERROR_PATTERNS = (
    re.compile(r"<title[^>]*>\s*(?:(?:403|5\d{2})\b|forbidden|internal server error)", re.I),
    re.compile(r"<h[12][^>]*>\s*(?:(?:403|5\d{2})\b|forbidden|internal server error)", re.I),
    re.compile(r"<title[^>]*>[^<]*(?:502|503|504|bad gateway|service unavailable|gateway timeout)", re.I),
    re.compile(r"(?:bad gateway|service unavailable|gateway timeout|origin error|web server is down)", re.I),
)
_NOT_FOUND_PATTERNS = (
    re.compile(
        r"<title[^>]*>\s*(?:404(?:\s|[-_|—:]|页面|page)|(?:页面|章节)不存在|(?:page|chapter)\s+not\s+found)",
        re.I,
    ),
    re.compile(r"(?:您访问的章节不存在|chapter\s+not\s+found|page\s+not\s+found)", re.I),
)
_CHAPTER_HEADING_RE = re.compile(
    r"^(?:第\s*)?(?:[0-9]{1,6}|[零〇一二两三四五六七八九十百千万]{1,12})\s*(?:章|节|回|卷|話|话)",
    re.I,
)
_BOILERPLATE_RE = re.compile(
    r"(上一章|下一章|返回目录|章节目录|加入书架|点击收藏|最新网址|本站域名|"
    r"手机阅读|本章未完|点击下一页|previous\s+chapter|next\s+chapter)",
    re.I,
)


def _normalize_inline(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_import_text(value)).strip()


def _normalize_paragraphs(value: str) -> str:
    lines = []
    for raw_line in normalize_import_text(value).splitlines():
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return normalize_import_text("\n\n".join(lines))


def _author_without_label(value: str) -> str:
    return re.sub(r"^(?:作者|作\s*者)\s*[:：]?\s*", "", value, flags=re.I).strip()


class DomParserFramework:
    """Offline DOM extraction pipeline shared by versioned source adapters."""

    def __init__(self, selectors: DomSelectorConfig, *, minimum_content_length: int = 20) -> None:
        self.selectors = selectors
        self.minimum_content_length = minimum_content_length

    @staticmethod
    def raise_for_page_state(html: str) -> None:
        sample = html[:200_000]
        if any(pattern.search(sample) for pattern in _CHALLENGE_PATTERNS):
            raise DomParserError(
                "Source verification page detected",
                "user_verification_required",
            )
        if any(pattern.search(sample) for pattern in _RATE_LIMIT_PATTERNS):
            raise DomParserError("Source rate limit page detected", "rate_limited")
        if any(pattern.search(sample) for pattern in _SOURCE_ERROR_PATTERNS):
            raise DomParserError("Source error page detected", "source_unavailable")
        if any(pattern.search(sample) for pattern in _NOT_FOUND_PATTERNS):
            raise DomParserError("Source content was not found", "content_not_found")

    def parse_preview(
        self,
        *,
        base_url: str,
        html: str,
        canonicalize_link: Callable[[str], str],
    ) -> DomPreviewData:
        self.raise_for_page_state(html)
        document = DomDocument(html)
        document.remove(self.selectors.remove_selectors)
        title = self._first_value(document, self.selectors.title)
        if not title:
            raise DomParserError("Book title selector did not match", "parse_failed", fallback_allowed=True)

        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for selector in self.selectors.chapter_links:
            for node in document.select_all(selector.query):
                href = node.attrs.get(selector.attribute or "href", "").strip()
                label = document.text_content(node)
                if not href or not label:
                    continue
                try:
                    canonical = canonicalize_link(urljoin(base_url, href))
                except ValueError:
                    continue
                if canonical in seen:
                    continue
                seen.add(canonical)
                links.append((label, canonical))
        if not links:
            raise DomParserError("Chapter link selectors did not match", "parse_failed", fallback_allowed=True)

        cover = self._first_value(document, self.selectors.cover)
        return DomPreviewData(
            title=title,
            author=_author_without_label(self._first_value(document, self.selectors.author)),
            description=self._first_value(document, self.selectors.description),
            cover_url=urljoin(base_url, cover) if cover else "",
            chapter_links=tuple(links),
        )

    def parse_chapter(self, *, html: str) -> DomChapterData:
        self.raise_for_page_state(html)
        document = DomDocument(html)
        document.remove(self.selectors.remove_selectors)
        title_selectors = self.selectors.chapter_title + self.selectors.title
        title = self._first_value(document, title_selectors)
        content_node = self._first_node(document, self.selectors.chapter_content)
        if content_node is None:
            raise DomParserError("Chapter content selector did not match", "parse_failed", fallback_allowed=True)

        chapter_link_nodes = [
            node
            for node in _iter_nodes(content_node)
            if node.tag == "a" and _CHAPTER_HEADING_RE.search(document.text_content(node))
        ]
        raw_text = document.paragraph_text(content_node)
        self.validate_content(raw_text, title=title, chapter_link_count=len(chapter_link_nodes))
        text = self.normalize_cleanup(raw_text)
        self.validate_content(text, title=title, chapter_link_count=len(chapter_link_nodes))
        return DomChapterData(title=title, text=text, content_hash=source_hash(text))

    @staticmethod
    def normalize_cleanup(text: str) -> str:
        return normalize_import_text(clean_chapter(_normalize_paragraphs(text)))

    def validate_content(
        self,
        text: str,
        *,
        title: str = "",
        chapter_link_count: int = 0,
    ) -> None:
        normalized = _normalize_paragraphs(text)
        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        if len(normalized) < self.minimum_content_length:
            raise DomParserError("Chapter content is empty or too short", "content_invalid")
        chapter_like = sum(bool(_CHAPTER_HEADING_RE.search(part)) for part in paragraphs)
        if chapter_like >= 3 and (
            "章节目录" in title or chapter_like / max(1, len(paragraphs)) >= 0.6
        ):
            raise DomParserError("Chapter list was detected instead of chapter content", "content_invalid")
        if chapter_link_count >= 3 and (
            chapter_like >= 3 or "章节目录" in title or chapter_link_count >= max(3, len(paragraphs) // 2)
        ):
            raise DomParserError("Chapter list was detected instead of chapter content", "content_invalid")
        boilerplate = sum(bool(_BOILERPLATE_RE.search(part)) for part in paragraphs)
        if paragraphs and boilerplate / len(paragraphs) >= 0.6:
            raise DomParserError("Chapter content contains too much navigation boilerplate", "content_invalid")

    @staticmethod
    def _first_node(document: DomDocument, selectors: tuple[DomSelector, ...]) -> DomNode | None:
        for selector in selectors:
            node = document.select_one(selector.query)
            if node is not None:
                return node
        return None

    @staticmethod
    def _first_value(document: DomDocument, selectors: tuple[DomSelector, ...]) -> str:
        for selector in selectors:
            node = document.select_one(selector.query)
            if node is None:
                continue
            value = node.attrs.get(selector.attribute, "") if selector.attribute else document.text_content(node)
            normalized = _normalize_inline(value)
            if normalized:
                return normalized
        return ""
