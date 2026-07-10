from __future__ import annotations

from dataclasses import dataclass, replace
import html as html_lib
from html.parser import HTMLParser
import posixpath
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urldefrag
import zipfile

from app.database.db import (
    add_book,
    add_chapter,
    get_book_by_id,
    get_book_by_title,
    get_chapter,
    record_ebook_import_run,
    update_book,
    update_chapter_paths,
)
from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.utils.chinese_numbers import parse_chinese_number


SUPPORTED_EBOOK_FORMATS = {"epub", "azw3", "mobi", "prc", "txt", "html", "htm"}
KINDLE_FORMATS = {"azw3", "mobi", "prc"}
SUPPORTED_SPLIT_MODES = {"auto", "single"}
PREVIEW_EDGE_CHAPTERS = 20
TOO_SHORT_CHAPTER_CHARS = 80
LOW_QUALITY_MIN_CHAPTERS = 5
LOW_QUALITY_TITLE_ONLY_RATIO = 0.8
LOW_QUALITY_SHORT_RATIO = 0.9
LOW_QUALITY_AVG_CHARS = 40
GARBAGE_DOCUMENT_MARKERS = ("cover", "titlepage", "toc", "contents", "copyright", "about", "nav")
SUSPECT_DOCUMENT_MARKERS = ("titlepage", "part0000")
MAX_INLINE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BOOK_ASSET_BYTES = 50 * 1024 * 1024


def _normalize_page_break_token(value: str | None) -> str:
    return re.sub(r"[_\s]+", "-", (value or "").lower()).strip()


def _style_value(style: str, property_name: str) -> str:
    pattern = re.compile(rf"(?:^|;)\s*{re.escape(property_name)}\s*:\s*([^;]+)", flags=re.IGNORECASE)
    match = pattern.search(style)
    return _normalize_page_break_token(match.group(1) if match else "")


def _style_has_page_break(style: str, direction: str) -> bool:
    properties = (
        ("break-before", "page-break-before")
        if direction == "before"
        else ("break-after", "page-break-after")
    )
    return any(_style_value(style, prop) in {"always", "left", "page", "recto", "right", "verso"} for prop in properties)


def _style_has_break_inside_avoid(style: str) -> bool:
    return any(
        (_style_value(style, prop) == "avoid" or _style_value(style, prop).startswith("avoid-"))
        for prop in ("break-inside", "page-break-inside", "column-break-inside", "-webkit-column-break-inside")
    )


def _split_css_selectors(selector_text: str) -> list[str]:
    return [selector.strip() for selector in selector_text.split(",") if selector.strip()]


def _extract_css_pagination_rules(stylesheet: str) -> list[dict]:
    rules: list[dict] = []
    stylesheet = re.sub(r"/\*[\s\S]*?\*/", " ", stylesheet)
    for rule_match in re.finditer(r"([^{}@]+)\{([^{}]+)\}", stylesheet):
        declarations = rule_match.group(2)
        hints = {
            "pageBreakAfter": _style_has_page_break(declarations, "after"),
            "pageBreakBefore": _style_has_page_break(declarations, "before"),
            "pageBreakInsideAvoid": _style_has_break_inside_avoid(declarations),
        }
        if not any(hints.values()):
            continue
        for selector in _split_css_selectors(rule_match.group(1)):
            rules.append({"selector": selector, **hints})
    return rules


def _css_import_hrefs(stylesheet: str) -> list[str]:
    clean_stylesheet = re.sub(r"/\*[\s\S]*?\*/", " ", stylesheet)
    hrefs: list[str] = []
    import_pattern = re.compile(
        r"@import\s+(?:url\(\s*)?(?:\"([^\"]+)\"|'([^']+)'|([^'\"\s;)]+))(?:\s*\))?",
        flags=re.IGNORECASE,
    )
    for match in import_pattern.finditer(clean_stylesheet):
        href = next((group for group in match.groups() if group), "").strip()
        if href:
            hrefs.append(html_lib.unescape(href))
    return hrefs


def _extract_stylesheet_pagination_rules(html: str) -> list[dict]:
    rules: list[dict] = []
    for style_match in re.finditer(r"<style\b[^>]*>([\s\S]*?)</style>", html, flags=re.IGNORECASE):
        rules.extend(_extract_css_pagination_rules(style_match.group(1)))
    return rules


def _html_attr_value(tag: str, attr_name: str) -> str:
    pattern = re.compile(
        rf"\b{re.escape(attr_name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>/]+))",
        flags=re.IGNORECASE,
    )
    match = pattern.search(tag)
    if not match:
        return ""
    return html_lib.unescape(next((group for group in match.groups() if group is not None), ""))


def _linked_stylesheet_hrefs(html: str) -> list[str]:
    hrefs: list[str] = []
    for tag_match in re.finditer(r"<link\b[^>]*>", html, flags=re.IGNORECASE):
        tag = tag_match.group(0)
        rel_tokens = set(_html_attr_value(tag, "rel").lower().split())
        if "stylesheet" not in rel_tokens:
            continue
        href = _html_attr_value(tag, "href").strip()
        if href:
            hrefs.append(href)
    return hrefs


def _resolve_epub_relative_path(source_zip_path: str, href: str) -> str:
    href_without_fragment = urldefrag(href)[0]
    if not href_without_fragment:
        return ""
    href_path = unquote(href_without_fragment)
    if href_path.startswith("/"):
        return posixpath.normpath(href_path.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_zip_path), href_path))


def _selector_matches_simple(tag: str, attrs: dict[str, str], selector: str) -> bool:
    selector_value = selector.strip()
    if not selector_value or any(token in selector_value for token in (" ", ">", "+", "~", "[", ":")):
        return False

    id_match = re.search(r"#([A-Za-z0-9_-]+)", selector_value)
    if id_match and attrs.get("id", "") != id_match.group(1):
        return False

    class_names = set(attrs.get("class", "").split())
    for class_name in re.findall(r"\.([A-Za-z0-9_-]+)", selector_value):
        if class_name not in class_names:
            return False

    tag_name = re.sub(r"[#.].*$", "", selector_value).strip().lower()
    if tag_name and tag_name != tag.lower():
        return False
    return bool(tag_name or id_match or "." in selector_value)


def _normalize_preserved_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


class _TextExtractor(HTMLParser):
    PARAGRAPH_TAGS = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
    LINE_BREAK_TAGS = {"br"}
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag_name = tag.lower().split(":")[-1]
        if tag_name in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag_name in self.LINE_BREAK_TAGS:
            self.parts.append("\n")
            return
        if tag_name in self.PARAGRAPH_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower().split(":")[-1]
        if tag_name in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag_name in self.PARAGRAPH_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return _normalize_preserved_text("".join(self.parts))


class _RichHtmlSanitizer(HTMLParser):
    ALLOWED_TAGS = {
        "article",
        "audio",
        "blockquote",
        "br",
        "caption",
        "code",
        "col",
        "colgroup",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "picture",
        "pre",
        "section",
        "source",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
        "video",
    }
    VOID_TAGS = {"br", "col", "hr", "img", "source"}
    SKIP_TAGS = {"script", "style", "head", "metadata", "svg", "object", "iframe"}
    BOOLEAN_ATTRS = {"controls"}
    ALLOWED_ATTRS = {
        "audio": {"aria-label", "controls", "preload", "src", "title"},
        "col": {"span", "width"},
        "img": {"alt", "height", "src", "title", "width"},
        "source": {"media", "src", "srcset", "type"},
        "td": {"colspan", "headers", "rowspan"},
        "th": {"colspan", "headers", "rowspan", "scope"},
        "video": {"aria-label", "controls", "height", "poster", "preload", "src", "title", "width"},
    }

    def __init__(self, stylesheet_rules: list[dict] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._body_depth = 0
        self._saw_body = False
        self._stylesheet_rules = stylesheet_rules or []

    def _should_emit(self) -> bool:
        return self._skip_depth == 0 and (not self._saw_body or self._body_depth > 0)

    @staticmethod
    def _attr_map(attrs) -> dict[str, str]:
        return {str(name).lower(): str(value or "") for name, value in attrs}

    def _stylesheet_hints(self, tag: str, attrs: dict[str, str]) -> dict[str, bool]:
        hints = {"after": False, "before": False, "inside": False}
        for rule in self._stylesheet_rules:
            selector = str(rule.get("selector") or "")
            if not _selector_matches_simple(tag, attrs, selector):
                continue
            hints["after"] = hints["after"] or bool(rule.get("pageBreakAfter"))
            hints["before"] = hints["before"] or bool(rule.get("pageBreakBefore"))
            hints["inside"] = hints["inside"] or bool(rule.get("pageBreakInsideAvoid"))
        return hints

    @staticmethod
    def _token_hints(attrs: dict[str, str]) -> dict[str, bool]:
        class_token = _normalize_page_break_token(attrs.get("class", ""))
        data_break = _normalize_page_break_token(attrs.get("data-break", ""))
        data_page_break = _normalize_page_break_token(attrs.get("data-page-break", ""))
        data_pagebreak = _normalize_page_break_token(attrs.get("data-pagebreak", ""))
        combined = " ".join(
            _normalize_page_break_token(value)
            for value in (
                attrs.get("class", ""),
                attrs.get("id", ""),
                attrs.get("epub:type", ""),
                attrs.get("role", ""),
                attrs.get("data-type", ""),
            )
        )
        before = (
            "data-break-before" in attrs
            or "data-page-break-before" in attrs
            or data_break == "before"
            or data_page_break == "before"
            or data_pagebreak == "before"
            or "page-break-before" in class_token
            or "break-before" in class_token
            or bool(re.search(r"\b(?:chapter-)?(?:epub-)?(?:mbp-)?page-?break\b", combined))
        )
        after = (
            "data-break-after" in attrs
            or "data-page-break-after" in attrs
            or data_break in {"after", "left", "right", "recto", "verso"}
            or data_page_break in {"after", "left", "right", "recto", "verso"}
            or data_pagebreak in {"after", "left", "right", "recto", "verso"}
            or "page-break-after" in class_token
            or "break-after" in class_token
        )
        inside = (
            _normalize_page_break_token(attrs.get("data-break-inside", "")) in {"avoid", "avoid-page"}
            or _normalize_page_break_token(attrs.get("data-page-break-inside", "")) in {"avoid", "avoid-page"}
            or _normalize_page_break_token(attrs.get("data-keep-together", "")) in {"1", "avoid", "true", "yes"}
            or _normalize_page_break_token(attrs.get("data-avoid-break", "")) in {"1", "avoid", "true", "yes"}
            or "keep-together" in class_token
            or "avoid-break" in class_token
            or "break-inside-avoid" in class_token
            or "page-break-inside-avoid" in class_token
        )
        return {"after": after, "before": before, "inside": inside}

    def _pagination_attrs(self, tag: str, attrs) -> list[str]:
        attr_map = self._attr_map(attrs)
        style = attr_map.get("style", "")
        stylesheet_hints = self._stylesheet_hints(tag, attr_map)
        token_hints = self._token_hints(attr_map)
        rendered: list[str] = []
        if _style_has_page_break(style, "before") or stylesheet_hints["before"] or token_hints["before"]:
            rendered.append('data-page-break-before="always"')
        if _style_has_page_break(style, "after") or stylesheet_hints["after"] or token_hints["after"]:
            rendered.append('data-page-break-after="always"')
        if _style_has_break_inside_avoid(style) or stylesheet_hints["inside"] or token_hints["inside"]:
            rendered.append('data-page-break-inside="avoid"')
        return rendered

    def _render_attrs(self, tag: str, attrs) -> str:
        allowed = self.ALLOWED_ATTRS.get(tag, set())
        rendered: list[str] = []
        for name, value in attrs:
            attr_name = name.lower()
            if attr_name not in allowed:
                continue
            if value is None:
                if attr_name in self.BOOLEAN_ATTRS:
                    rendered.append(attr_name)
                continue
            rendered.append(f'{attr_name}="{html_lib.escape(value, quote=True)}"')
        rendered.extend(self._pagination_attrs(tag, attrs))
        return f" {' '.join(rendered)}" if rendered else ""

    def handle_starttag(self, tag: str, attrs) -> None:
        tag_name = tag.lower().split(":")[-1]
        if tag_name == "body":
            self._saw_body = True
            self._body_depth += 1
            return
        if tag_name in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if not self._should_emit() or tag_name not in self.ALLOWED_TAGS:
            return
        self.parts.append(f"<{tag_name}{self._render_attrs(tag_name, attrs)}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower().split(":")[-1]
        if tag_name == "body":
            if self._body_depth:
                self._body_depth -= 1
            return
        if tag_name in self.SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if not self._should_emit() or tag_name not in self.ALLOWED_TAGS or tag_name in self.VOID_TAGS:
            return
        self.parts.append(f"</{tag_name}>")

    def handle_data(self, data: str) -> None:
        if self._should_emit():
            self.parts.append(html_lib.escape(data))

    def html(self) -> str:
        compact = re.sub(r"\n{3,}", "\n\n", "".join(self.parts))
        return compact.strip()


@dataclass(frozen=True)
class ParsedEbookChapter:
    chapter_number: int
    title: str
    text: str
    source_path: str = ""
    html: str = ""
    html_source_path: str = ""


@dataclass(frozen=True)
class ParsedEbookCover:
    content: bytes
    href: str
    media_type: str


@dataclass(frozen=True)
class EpubManifestItem:
    item_id: str
    href: str
    media_type: str
    properties: str = ""


@dataclass(frozen=True)
class ParsedEbookAsset:
    href: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class EpubTocEntry:
    title: str
    href: str
    fragment: str
    order: int


@dataclass(frozen=True)
class ChapterHeadingMatch:
    number: int | None
    title: str
    raw: str


@dataclass(frozen=True)
class ParsedEbook:
    title: str
    author: str
    language: str
    source_format: str
    cover_present: bool
    cover: ParsedEbookCover | None
    chapters: list[ParsedEbookChapter]
    assets: dict[str, ParsedEbookAsset]
    warnings: list[dict]
    split_method: str
    toc_chapter_count: int


def _xml_text(root: ET.Element, local_name: str) -> str:
    for element in root.iter():
        if element.tag.split("}")[-1] == local_name and element.text:
            return element.text.strip()
    return ""


def _attr(element: ET.Element, name: str) -> str:
    return str(element.attrib.get(name) or element.attrib.get(f"{{http://www.w3.org/1999/xlink}}{name}") or "")


def _local_attr(element: ET.Element, name: str) -> str:
    for attr_name, value in element.attrib.items():
        if attr_name.split("}")[-1] == name:
            return str(value)
    return ""


def _html_to_text(value: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(value.decode("utf-8", errors="ignore"))
    parser.close()
    return parser.text()


def _html_to_sanitized_html(value: bytes, stylesheet_rules: list[dict] | None = None) -> str:
    decoded = value.decode("utf-8", errors="ignore")
    parser = _RichHtmlSanitizer(stylesheet_rules or _extract_stylesheet_pagination_rules(decoded))
    parser.feed(decoded)
    parser.close()
    return parser.html()


def _strip_heading_title(value: str) -> str:
    return re.sub(r"^[\s:：.\-–—]+", "", value).strip()


def _parse_heading_match(line: str) -> ChapterHeadingMatch | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 140:
        return None

    patterns = [
        r"^\s*(?:Ch(?:ương|uong|\.)?|Chap(?:ter)?|Chapter)\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[:：.\-–—\s]*(.*)$",
        r"^\s*(?:Hồi|Hoi|Quyển|Quyen|Phần|Phan|Tập|Tap)\s+([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[:：.\-–—\s]*(.*)$",
        r"^\s*第\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节話话回卷]\s*[:：.\-–—\s]*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        number = parse_chinese_number(match.group(1))
        if number is None:
            continue
        return ChapterHeadingMatch(number=number, title=_strip_heading_title(match.group(2)), raw=stripped)

    special_heading = re.match(
        r"^\s*(?:ngoại\s*truyện|ngoai\s*truyen|phiên\s*ngoại|phien\s*ngoai|extra|side\s*story|"
        r"mở\s*đầu|mo\s*dau|lời\s*tựa|loi\s*tua|tựa|prologue|preface|introduction|"
        r"kết|ket|kết\s*thúc|ket\s*thuc|hoàn|hoan|epilogue|afterword)"
        r"(?:\s*[0-9]{0,5})?\s*[:：.\-–—]?\s*(.*)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if special_heading:
        return ChapterHeadingMatch(number=None, title=stripped, raw=stripped)

    return None


def _parse_heading(line: str) -> tuple[int | None, str]:
    heading = _parse_heading_match(line)
    if not heading:
        return None, ""
    return heading.number, heading.title


def _chapter_from_text(
    text: str,
    fallback_number: int,
    fallback_title: str = "",
    source_path: str = "",
    html: str = "",
    html_source_path: str = "",
) -> ParsedEbookChapter | None:
    normalized_text = _normalize_preserved_text(text)
    raw_lines = [line.strip() for line in normalized_text.splitlines()]
    content_line_indexes = [index for index, line in enumerate(raw_lines) if line]
    if not content_line_indexes:
        return None

    heading_index = next(
        (
            line_index
            for line_index in content_line_indexes[:4]
            if _parse_heading_match(raw_lines[line_index])
        ),
        None,
    )
    heading = _parse_heading_match(raw_lines[heading_index]) if heading_index is not None else None
    if heading:
        body_text = _normalize_preserved_text("\n".join(raw_lines[heading_index + 1:]))
        chapter_text = body_text or raw_lines[heading_index]
        chapter_title = heading.title or fallback_title or raw_lines[heading_index]
        return ParsedEbookChapter(
            heading.number or fallback_number,
            chapter_title,
            chapter_text,
            source_path,
            html,
            html_source_path,
        )

    return ParsedEbookChapter(
        fallback_number,
        fallback_title or f"Chương {fallback_number}",
        normalized_text,
        source_path,
        html,
        html_source_path,
    )


def _split_by_headings(text: str, source_path: str = "") -> list[ParsedEbookChapter]:
    chapters: list[ParsedEbookChapter] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in _normalize_preserved_text(text).splitlines():
        stripped = line.strip()
        if stripped and _parse_heading_match(stripped):
            if current_heading and any(item.strip() for item in current_lines):
                parsed = _chapter_from_text(
                    "\n".join([current_heading, *current_lines]),
                    len(chapters) + 1,
                    source_path=source_path,
                )
                if parsed:
                    chapters.append(parsed)
            current_heading = stripped
            current_lines = []
            continue
        if current_heading is not None:
            current_lines.append(stripped)

    if current_heading and any(item.strip() for item in current_lines):
        parsed = _chapter_from_text(
            "\n".join([current_heading, *current_lines]),
            len(chapters) + 1,
            source_path=source_path,
        )
        if parsed:
            chapters.append(parsed)

    return chapters


def _join_zip_path(base_path: str, href: str) -> str:
    base = PurePosixPath(base_path).parent
    href_without_fragment, _fragment = urldefrag(href)
    joined = str(base.joinpath(unquote(href_without_fragment)))
    return posixpath.normpath(joined).lstrip("/")


def _split_href_fragment(href: str) -> tuple[str, str]:
    href_without_fragment, fragment = urldefrag(href)
    return unquote(href_without_fragment), unquote(fragment)


def _display_filename_stem(value: str) -> str:
    stem = Path(value).stem.strip()
    return stem or "ebook"


def _normalized_identifier(*parts: str) -> str:
    return " ".join(parts).replace("_", "").replace("-", "").replace(" ", "").lower()


def _normalized_content_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()


def _chapter_text_char_count(chapter: ParsedEbookChapter) -> int:
    return len(re.sub(r"\s+", "", chapter.text))


def _chapter_looks_title_only(chapter: ParsedEbookChapter) -> bool:
    text_key = _normalized_content_key(chapter.text)
    if not text_key or len(text_key) > 120:
        return False

    title = chapter.title.strip()
    candidates = [
        title,
        f"Chương {chapter.chapter_number} {title}",
        f"Chuong {chapter.chapter_number} {title}",
        f"Chapter {chapter.chapter_number} {title}",
        f"Hồi {chapter.chapter_number} {title}",
        f"Hoi {chapter.chapter_number} {title}",
    ]
    candidate_keys = {_normalized_content_key(candidate) for candidate in candidates if candidate.strip()}
    return text_key in candidate_keys


def _chapter_quality(chapters: list[ParsedEbookChapter]) -> dict[str, float | int]:
    total = len(chapters)
    text_chars = [_chapter_text_char_count(chapter) for chapter in chapters]
    short_count = sum(1 for count in text_chars if count < TOO_SHORT_CHAPTER_CHARS)
    title_only_count = sum(1 for chapter in chapters if _chapter_looks_title_only(chapter))
    total_chars = sum(text_chars)
    return {
        "chapter_count": total,
        "total_chars": total_chars,
        "avg_chars": (total_chars / total) if total else 0,
        "short_count": short_count,
        "title_only_count": title_only_count,
        "short_ratio": (short_count / total) if total else 0,
        "title_only_ratio": (title_only_count / total) if total else 0,
    }


def _chapter_quality_score(chapters: list[ParsedEbookChapter]) -> float:
    quality = _chapter_quality(chapters)
    chapter_count = int(quality["chapter_count"])
    title_only_count = int(quality["title_only_count"])
    short_count = int(quality["short_count"])
    readable_count = max(0, chapter_count - short_count)
    body_like_count = max(0, chapter_count - title_only_count)
    return float(quality["total_chars"]) + readable_count * TOO_SHORT_CHAPTER_CHARS + body_like_count * 40


def _is_low_quality_chapter_set(chapters: list[ParsedEbookChapter]) -> bool:
    quality = _chapter_quality(chapters)
    if int(quality["chapter_count"]) < LOW_QUALITY_MIN_CHAPTERS:
        return False
    if float(quality["title_only_ratio"]) >= LOW_QUALITY_TITLE_ONLY_RATIO:
        return True
    return (
        float(quality["short_ratio"]) >= LOW_QUALITY_SHORT_RATIO
        and float(quality["avg_chars"]) < LOW_QUALITY_AVG_CHARS
    )


def _chapter_payload(chapter: ParsedEbookChapter) -> dict:
    return {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "sample": chapter.text[:240],
    }


def _preview_edges(chapters: list[ParsedEbookChapter]) -> tuple[list[dict], list[dict], list[dict]]:
    first = [_chapter_payload(chapter) for chapter in chapters[:PREVIEW_EDGE_CHAPTERS]]
    last_source = chapters[-PREVIEW_EDGE_CHAPTERS:] if len(chapters) > PREVIEW_EDGE_CHAPTERS else chapters
    last = [_chapter_payload(chapter) for chapter in last_source]
    combined: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for item in [*first, *last]:
        key = (int(item["chapter_number"]), str(item["title"]))
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)
    return first, last, combined


def _renumber_if_needed(chapters: list[ParsedEbookChapter]) -> tuple[list[ParsedEbookChapter], bool]:
    seen: set[int] = set()
    needs_renumber = False
    for chapter in chapters:
        if chapter.chapter_number <= 0 or chapter.chapter_number in seen:
            needs_renumber = True
            break
        seen.add(chapter.chapter_number)

    if not needs_renumber:
        return chapters, False

    return [
        replace(chapter, chapter_number=index)
        for index, chapter in enumerate(chapters, start=1)
    ], True


def _warning(warning_type: str, message: str, chapter: ParsedEbookChapter | None = None) -> dict:
    payload = {"type": warning_type, "message": message}
    if chapter is not None:
        payload["chapter_number"] = chapter.chapter_number
        payload["title"] = chapter.title
    return payload


class EbookImportService:
    def __init__(self, db_path: Path | None = None, data_dir: Path | None = None) -> None:
        self.db_path = db_path or get_db_path()
        self.data_dir = data_dir or get_data_dir()

    def _stylesheet_pagination_rules_from_epub_css(
        self,
        epub: zipfile.ZipFile,
        css_path: str,
        seen_paths: set[str],
    ) -> list[dict]:
        if not css_path or css_path in seen_paths:
            return []
        seen_paths.add(css_path)
        try:
            css = epub.read(css_path).decode("utf-8", errors="ignore")
        except KeyError:
            return []

        rules = _extract_css_pagination_rules(css)
        for href in _css_import_hrefs(css):
            imported_path = _resolve_epub_relative_path(css_path, href)
            rules.extend(self._stylesheet_pagination_rules_from_epub_css(epub, imported_path, seen_paths))
        return rules

    def _stylesheet_pagination_rules_for_epub_document(
        self,
        epub: zipfile.ZipFile,
        source_zip_path: str,
        content: bytes,
    ) -> list[dict]:
        decoded = content.decode("utf-8", errors="ignore")
        rules = _extract_stylesheet_pagination_rules(decoded)
        seen_paths: set[str] = set()
        for href in _linked_stylesheet_hrefs(decoded):
            css_path = _resolve_epub_relative_path(source_zip_path, href)
            if not css_path or css_path in seen_paths:
                continue
            rules.extend(self._stylesheet_pagination_rules_from_epub_css(epub, css_path, seen_paths))
        return rules

    def preview(
        self,
        file_path: Path,
        *,
        split_mode: str = "auto",
        target_book_id: int | None = None,
        duplicate_strategy: str = "skip",
        original_filename: str = "",
    ) -> dict:
        if duplicate_strategy not in {"error", "skip", "overwrite"}:
            raise ValueError("duplicate_strategy must be one of: error, skip, overwrite")

        parsed = self._parse(file_path, split_mode=split_mode, original_filename=original_filename)
        first_chapters, last_chapters, preview_chapters = _preview_edges(parsed.chapters)
        _cover_path, cover_preview_url = self._save_cover(parsed, "previews", "preview")
        return {
            "title": parsed.title,
            "author": parsed.author,
            "language": parsed.language,
            "source_format": parsed.source_format,
            "cover_present": parsed.cover_present,
            "cover_preview_url": cover_preview_url,
            "chapter_count": len(parsed.chapters),
            "split_method": parsed.split_method,
            "toc_chapter_count": parsed.toc_chapter_count,
            "chapters": preview_chapters,
            "first_chapters": first_chapters,
            "last_chapters": last_chapters,
            "warnings": parsed.warnings,
            "dry_run": self._dry_run_for_parsed(
                parsed,
                target_book_id=target_book_id,
                duplicate_strategy=duplicate_strategy,
            ),
        }

    def import_translated_ebook(
        self,
        file_path: Path,
        *,
        target_book_id: int | None = None,
        duplicate_strategy: str = "skip",
        split_mode: str = "auto",
        original_filename: str = "",
    ) -> dict:
        if duplicate_strategy not in {"error", "skip", "overwrite"}:
            raise ValueError("duplicate_strategy must be one of: error, skip, overwrite")

        parsed = self._parse(file_path, split_mode=split_mode, original_filename=original_filename)
        self._raise_if_unreadable(parsed)
        book_id = self._resolve_book_id(parsed, target_book_id)
        cover_path, cover_url = self._save_cover(parsed, "", f"book_{book_id}")
        if cover_path:
            update_book(self.db_path, book_id, cover_path=cover_path)
        imported = 0
        skipped = 0
        overwritten = 0
        chapter_ids: list[int] = []

        for chapter in parsed.chapters:
            existing = get_chapter(self.db_path, book_id, chapter.chapter_number)
            if existing and duplicate_strategy == "skip":
                skipped += 1
                continue
            if existing and duplicate_strategy == "error":
                raise ValueError(f"Duplicate chapter number {chapter.chapter_number} for book {book_id}")

            raw_path = self._write_raw_chapter(parsed.title, chapter)
            translated_path = self._write_translated_chapter(parsed.title, chapter)
            content_html = self._prepare_chapter_html(parsed, book_id, chapter)
            content_html_path = self._write_chapter_html(parsed.title, chapter, content_html) if content_html else None
            if existing:
                chapter_id = int(existing["id"])
                overwritten += 1
            else:
                chapter_id = add_chapter(
                    self.db_path,
                    book_id,
                    chapter.chapter_number,
                    chapter.title,
                    source_url=str(file_path.name),
                    raw_text_path=raw_path,
                    adapter_id="ebook",
                )
            update_chapter_paths(
                self.db_path,
                chapter_id,
                raw_text_path=raw_path,
                translated_text_path=translated_path,
                content_html_path=content_html_path,
                clear_content_html_path=content_html_path is None,
                status="translated",
            )
            chapter_ids.append(chapter_id)
            imported += 1

        result = {
            "book_id": book_id,
            "title": parsed.title,
            "author": parsed.author,
            "source_format": parsed.source_format,
            "chapter_count": len(parsed.chapters),
            "split_method": parsed.split_method,
            "toc_chapter_count": parsed.toc_chapter_count,
            "imported_chapters": imported,
            "skipped_chapters": skipped,
            "overwritten_chapters": overwritten,
            "chapter_ids": chapter_ids,
            "warnings": parsed.warnings,
            "cover_url": cover_url,
        }
        record_ebook_import_run(
            self.db_path,
            book_id=book_id,
            title=parsed.title,
            filename=original_filename or file_path.name,
            source_format=parsed.source_format,
            duplicate_strategy=duplicate_strategy,
            split_mode=split_mode,
            chapter_count=len(parsed.chapters),
            imported_chapters=imported,
            skipped_chapters=skipped,
            overwritten_chapters=overwritten,
            warnings=parsed.warnings,
        )
        return result

    def _dry_run_for_parsed(
        self,
        parsed: ParsedEbook,
        *,
        target_book_id: int | None,
        duplicate_strategy: str,
    ) -> dict:
        book_id = self._existing_book_id(parsed, target_book_id)
        duplicate_count = 0
        if book_id is not None:
            for chapter in parsed.chapters:
                if get_chapter(self.db_path, book_id, chapter.chapter_number):
                    duplicate_count += 1

        new_count = len(parsed.chapters) - duplicate_count
        would_skip = duplicate_count if duplicate_strategy == "skip" else 0
        would_overwrite = duplicate_count if duplicate_strategy == "overwrite" else 0
        would_error = duplicate_count if duplicate_strategy == "error" else 0
        would_import = new_count + would_overwrite
        return {
            "target_book_id": book_id,
            "target_title": parsed.title,
            "duplicate_strategy": duplicate_strategy,
            "chapter_count": len(parsed.chapters),
            "new_chapters": new_count,
            "duplicate_chapters": duplicate_count,
            "would_import": would_import,
            "would_skip": would_skip,
            "would_overwrite": would_overwrite,
            "would_error": would_error,
        }

    def _warnings_with_content_quality(
        self,
        chapters: list[ParsedEbookChapter],
        warnings: list[dict],
    ) -> list[dict]:
        if not _is_low_quality_chapter_set(chapters):
            return warnings
        if any(warning.get("type") == "unreadable_ebook" for warning in warnings):
            return warnings
        quality = _chapter_quality(chapters)
        return [
            *warnings,
            _warning(
                "unreadable_ebook",
                "Ebook gần như chỉ có tên chương/ảnh minh họa, không có nội dung chữ để đọc. "
                f"{int(quality['title_only_count'])}/{int(quality['chapter_count'])} chương giống tiêu đề.",
            ),
        ]

    def _raise_if_unreadable(self, parsed: ParsedEbook) -> None:
        if not any(warning.get("type") == "unreadable_ebook" for warning in parsed.warnings):
            return
        raise ValueError(
            "Ebook này gần như chỉ có tên chương/ảnh minh họa, không có nội dung chữ để đọc hoặc dịch. "
            "Hãy dùng EPUB/TXT/HTML có text thật, hoặc chạy OCR trước rồi import lại."
        )

    def _existing_book_id(self, parsed: ParsedEbook, target_book_id: int | None) -> int | None:
        if target_book_id is not None:
            if not get_book_by_id(self.db_path, target_book_id):
                raise ValueError(f"Book {target_book_id} not found")
            return target_book_id

        existing = get_book_by_title(self.db_path, parsed.title)
        return int(existing["id"]) if existing else None

    def _resolve_book_id(self, parsed: ParsedEbook, target_book_id: int | None) -> int:
        if target_book_id is not None:
            if not get_book_by_id(self.db_path, target_book_id):
                raise ValueError(f"Book {target_book_id} not found")
            return target_book_id

        existing = get_book_by_title(self.db_path, parsed.title)
        if existing:
            return int(existing["id"])
        return add_book(self.db_path, parsed.title, parsed.author, "ebook", "")

    def _write_raw_chapter(self, book_title: str, chapter: ParsedEbookChapter) -> Path:
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[\W_]+", "_", book_title, flags=re.UNICODE).strip("_") or "ebook"
        raw_path = raw_dir / f"{safe_title}_ch{chapter.chapter_number}_ebook_{time.time_ns()}.txt"
        raw_path.write_text(chapter.text, encoding="utf-8")
        return raw_path

    def _write_translated_chapter(self, book_title: str, chapter: ParsedEbookChapter) -> Path:
        translated_dir = self.data_dir / "translated"
        translated_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[\W_]+", "_", book_title, flags=re.UNICODE).strip("_") or "ebook"
        translated_path = translated_dir / f"{safe_title}_ch{chapter.chapter_number}_{time.time_ns()}.txt"
        translated_path.write_text(chapter.text, encoding="utf-8")
        return translated_path

    def _write_chapter_html(self, book_title: str, chapter: ParsedEbookChapter, content_html: str) -> Path:
        translated_dir = self.data_dir / "translated"
        translated_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[\W_]+", "_", book_title, flags=re.UNICODE).strip("_") or "ebook"
        html_path = translated_dir / f"{safe_title}_ch{chapter.chapter_number}_{time.time_ns()}.html"
        html_path.write_text(content_html, encoding="utf-8")
        return html_path

    @staticmethod
    def _safe_asset_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).name).strip("._-")
        return safe or "image"

    @staticmethod
    def _resolve_html_asset_key(source_path: str, src: str) -> str:
        src_value = html_lib.unescape(src).strip()
        if not src_value:
            return ""
        lower_src = src_value.lower()
        if lower_src.startswith(("http://", "https://", "data:", "javascript:", "#", "/")):
            return ""
        href_without_fragment, _fragment = urldefrag(src_value)
        base = PurePosixPath(source_path).parent
        return posixpath.normpath(str(base.joinpath(unquote(href_without_fragment)))).lstrip("/")

    def _prepare_chapter_html(self, parsed: ParsedEbook, book_id: int, chapter: ParsedEbookChapter) -> str:
        if not chapter.html:
            return ""
        asset_dir = self.data_dir / "book_assets" / str(book_id)
        copied_by_key: dict[str, str] = {}
        image_index = 0

        def local_asset_url(src: str) -> str:
            nonlocal image_index
            asset_key = self._resolve_html_asset_key(chapter.html_source_path, src)
            asset = parsed.assets.get(asset_key)
            if asset is None:
                return ""
            if asset_key not in copied_by_key:
                asset_dir.mkdir(parents=True, exist_ok=True)
                image_index += 1
                safe_name = self._safe_asset_name(asset.href)
                destination = asset_dir / f"ch{chapter.chapter_number}_{image_index}_{safe_name}"
                destination.write_bytes(asset.content)
                copied_by_key[asset_key] = f"/book-assets/{book_id}/{destination.name}"
            return copied_by_key[asset_key]

        def local_srcset_value(value: str) -> str:
            candidates: list[str] = []
            for raw_candidate in value.split(","):
                candidate = raw_candidate.strip()
                if not candidate:
                    continue
                parts = candidate.split(None, 1)
                asset_url = local_asset_url(parts[0])
                if asset_url:
                    descriptor = f" {parts[1].strip()}" if len(parts) > 1 and parts[1].strip() else ""
                    candidates.append(f"{asset_url}{descriptor}")
            return ", ".join(candidates)

        asset_tag_pattern = re.compile(r"<(?:img|source|audio|video)\b[^>]*>", flags=re.IGNORECASE)
        asset_attr_pattern = re.compile(r'(\s)(src|poster|srcset)="([^"]+)(")', flags=re.IGNORECASE)

        def replace_asset_tag(match: re.Match[str]) -> str:
            tag_html = match.group(0)

            def replace_asset_attr(attr_match: re.Match[str]) -> str:
                attr_name = attr_match.group(2)
                attr_value = attr_match.group(3)
                if attr_name.lower() == "srcset":
                    srcset_value = local_srcset_value(attr_value)
                    if not srcset_value:
                        return ""
                    return f'{attr_match.group(1)}{attr_name}="{srcset_value}{attr_match.group(4)}'

                asset_url = local_asset_url(attr_value)
                if not asset_url:
                    return ""
                return f'{attr_match.group(1)}{attr_name}="{asset_url}{attr_match.group(4)}'

            return asset_attr_pattern.sub(replace_asset_attr, tag_html)

        return asset_tag_pattern.sub(replace_asset_tag, chapter.html)

    def _cover_url(self, cover_path: Path | str) -> str:
        covers_dir = self.data_dir / "covers"
        path = Path(cover_path)
        try:
            relative_path = path.relative_to(covers_dir)
        except ValueError:
            return ""
        return f"/covers/{relative_path.as_posix()}"

    @staticmethod
    def _cover_extension(cover: ParsedEbookCover) -> str:
        suffix = Path(cover.href).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return suffix
        return {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(cover.media_type.lower(), ".jpg")

    @staticmethod
    def _safe_cover_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
        return safe or "cover"

    def _save_cover(self, parsed: ParsedEbook, subdir: str, prefix: str) -> tuple[str, str]:
        if not parsed.cover:
            return "", ""
        covers_dir = self.data_dir / "covers"
        if subdir:
            covers_dir = covers_dir / subdir
        covers_dir.mkdir(parents=True, exist_ok=True)
        extension = self._cover_extension(parsed.cover)
        safe_prefix = self._safe_cover_name(prefix)
        cover_path = covers_dir / f"{safe_prefix}_{time.time_ns()}{extension}"
        cover_path.write_bytes(parsed.cover.content)
        return str(cover_path), self._cover_url(cover_path)

    def _parse(self, file_path: Path, *, split_mode: str = "auto", original_filename: str = "") -> ParsedEbook:
        if split_mode not in SUPPORTED_SPLIT_MODES:
            raise ValueError("split_mode must be one of: auto, single")

        suffix = file_path.suffix.lower().lstrip(".")
        if suffix not in SUPPORTED_EBOOK_FORMATS:
            raise ValueError("Unsupported ebook format")
        if suffix == "epub":
            return self._parse_epub(
                file_path,
                source_format=suffix,
                split_mode=split_mode,
                original_filename=original_filename,
            )
        if suffix == "txt":
            return self._parse_plain_text(
                file_path,
                source_format=suffix,
                split_mode=split_mode,
                original_filename=original_filename,
            )
        if suffix in {"html", "htm"}:
            return self._parse_html_file(
                file_path,
                source_format="html",
                split_mode=split_mode,
                original_filename=original_filename,
            )

        with tempfile.TemporaryDirectory(prefix="ebook-import-") as temp_dir:
            converted = Path(temp_dir) / f"{file_path.stem}.epub"
            self._convert_to_epub(file_path, converted)
            return self._parse_epub(
                converted,
                source_format=suffix,
                split_mode=split_mode,
                original_filename=original_filename,
            )

    def _parse_text_publication(
        self,
        *,
        title: str,
        text: str,
        source_format: str,
        source_path: str,
        split_mode: str,
        html: str = "",
    ) -> ParsedEbook:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        warnings: list[dict] = []

        if split_mode == "single":
            chapters = [ParsedEbookChapter(1, "Toàn bộ ebook", normalized_text, source_path, html, source_path)]
            split_method = "single"
        else:
            chapters = _split_by_headings(normalized_text, source_path=source_path)
            if chapters:
                split_method = "regex"
                warnings.append(
                    _warning(
                        "regex_chapter_detection",
                        "App đã tự tạo danh sách chương từ heading text; hãy kiểm tra trước khi import.",
                    )
                )
            else:
                chapter = _chapter_from_text(
                    normalized_text,
                    1,
                    "Toàn bộ ebook",
                    source_path,
                    html=html,
                    html_source_path=source_path,
                )
                chapters = [chapter] if chapter else []
                split_method = "single"

        if not chapters:
            raise ValueError("No readable text chapters found")

        chapters, renumbered = _renumber_if_needed(chapters)
        if renumbered:
            warnings.append(
                _warning(
                    "chapter_numbers_normalized",
                    "App đã chuẩn hóa lại số chương theo thứ tự đọc để tránh trùng chương.",
                )
            )

        for chapter in chapters:
            warnings.extend(self._chapter_warnings(chapter))
        warnings = self._warnings_with_content_quality(chapters, warnings)

        return ParsedEbook(
            title=title,
            author="",
            language="vi",
            source_format=source_format,
            cover_present=False,
            cover=None,
            chapters=chapters,
            assets={},
            warnings=warnings,
            split_method=split_method,
            toc_chapter_count=0,
        )

    def _parse_plain_text(
        self,
        file_path: Path,
        *,
        source_format: str,
        split_mode: str,
        original_filename: str,
    ) -> ParsedEbook:
        text = file_path.read_text(encoding="utf-8-sig", errors="ignore")
        return self._parse_text_publication(
            title=_display_filename_stem(original_filename or file_path.name),
            text=text,
            source_format=source_format,
            source_path=file_path.name,
            split_mode=split_mode,
        )

    def _parse_html_file(
        self,
        file_path: Path,
        *,
        source_format: str,
        split_mode: str,
        original_filename: str,
    ) -> ParsedEbook:
        content = file_path.read_bytes()
        text = _html_to_text(content)
        html = _html_to_sanitized_html(content)
        return self._parse_text_publication(
            title=_display_filename_stem(original_filename or file_path.name),
            text=text,
            source_format=source_format,
            source_path=file_path.name,
            split_mode=split_mode,
            html=html,
        )

    def _convert_to_epub(self, input_path: Path, output_path: Path) -> None:
        converter = shutil.which("ebook-convert")
        if not converter:
            raise ValueError("Calibre ebook-convert is required for AZW3/MOBI/PRC import")
        try:
            subprocess.run(
                [converter, str(input_path), str(output_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise ValueError(f"ebook-convert failed; DRM-protected files are not supported. {detail}") from exc

    def _parse_epub(
        self,
        file_path: Path,
        *,
        source_format: str,
        split_mode: str,
        original_filename: str,
    ) -> ParsedEbook:
        with zipfile.ZipFile(file_path) as epub:
            container = ET.fromstring(epub.read("META-INF/container.xml"))
            rootfile = next(
                (
                    _attr(element, "full-path")
                    for element in container.iter()
                    if element.tag.split("}")[-1] == "rootfile" and _attr(element, "full-path")
                ),
                "",
            )
            if not rootfile:
                raise ValueError("EPUB container rootfile not found")

            opf_root = ET.fromstring(epub.read(rootfile))
            title = _xml_text(opf_root, "title") or _display_filename_stem(original_filename or file_path.name)
            author = _xml_text(opf_root, "creator")
            language = _xml_text(opf_root, "language")

            manifest: dict[str, EpubManifestItem] = {}
            cover_id = ""
            spine_toc_id = ""
            for element in opf_root.iter():
                local = element.tag.split("}")[-1]
                if local == "meta" and element.attrib.get("name") == "cover":
                    cover_id = str(element.attrib.get("content") or "")
                if local == "item":
                    item_id = str(element.attrib.get("id") or "")
                    href = str(element.attrib.get("href") or "")
                    media_type = str(element.attrib.get("media-type") or "")
                    properties = str(element.attrib.get("properties") or "")
                    if item_id and href:
                        manifest[item_id] = EpubManifestItem(item_id, href, media_type, properties)
                if local == "spine":
                    spine_toc_id = str(element.attrib.get("toc") or "")

            spine_refs = [
                str(element.attrib.get("idref") or "")
                for element in opf_root.iter()
                if element.tag.split("}")[-1] == "itemref" and element.attrib.get("idref")
            ]

            if split_mode == "single":
                chapters, warnings, split_method = self._chapters_from_spine(
                    epub,
                    rootfile,
                    manifest,
                    spine_refs,
                    split_mode=split_mode,
                )
                toc_chapter_count = 0
            else:
                toc_entries = self._extract_toc_entries(epub, rootfile, manifest, spine_toc_id)
                chapters, warnings, split_method = [], [], "spine"
                toc_chapter_count = 0
                if toc_entries:
                    chapters, warnings = self._chapters_from_toc(epub, rootfile, toc_entries)
                    toc_chapter_count = len(chapters)
                    if chapters:
                        split_method = "toc"
                        if _is_low_quality_chapter_set(chapters):
                            fallback_chapters, fallback_warnings, fallback_method = self._chapters_from_spine(
                                epub,
                                rootfile,
                                manifest,
                                spine_refs,
                                split_mode=split_mode,
                            )
                            if fallback_chapters and _chapter_quality_score(fallback_chapters) > _chapter_quality_score(chapters):
                                warnings.extend(fallback_warnings)
                                warnings.append(
                                    _warning(
                                        "toc_low_quality_fallback",
                                        "Mục lục trỏ tới các chương quá ngắn; app đã dùng spine EPUB để lấy nội dung chữ.",
                                    )
                                )
                                chapters = fallback_chapters
                                split_method = fallback_method
                    else:
                        warnings.append(_warning("toc_unmapped", "Có mục lục nhưng không map được chapter"))

                if not chapters:
                    fallback_chapters, fallback_warnings, fallback_method = self._chapters_from_spine(
                        epub,
                        rootfile,
                        manifest,
                        spine_refs,
                        split_mode=split_mode,
                    )
                    chapters = fallback_chapters
                    warnings.extend(fallback_warnings)
                    split_method = fallback_method

            cover = self._extract_cover(epub, rootfile, manifest, cover_id)
            cover_present = cover is not None
            assets = self._extract_assets(epub, rootfile, manifest)
            if not chapters:
                raise ValueError("No readable EPUB chapters found")
            warnings = self._warnings_with_content_quality(chapters, warnings)

            return ParsedEbook(
                title=title,
                author=author,
                language=language,
                source_format=source_format,
                cover_present=cover_present,
                cover=cover,
                chapters=chapters,
                assets=assets,
                warnings=warnings,
                split_method=split_method,
                toc_chapter_count=toc_chapter_count,
            )

    def _chapters_from_spine(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
        spine_refs: list[str],
        *,
        split_mode: str,
    ) -> tuple[list[ParsedEbookChapter], list[dict], str]:
        chapters: list[ParsedEbookChapter] = []
        single_mode_parts: list[str] = []
        warnings: list[dict] = []
        used_heading_split = False

        for idref in spine_refs:
            manifest_item = manifest.get(idref)
            if not manifest_item:
                continue
            href = manifest_item.href
            media_type = manifest_item.media_type
            if media_type and "html" not in media_type:
                continue
            source_path = Path(_split_href_fragment(href)[0]).stem
            source_zip_path = _join_zip_path(rootfile, href)
            try:
                content = epub.read(source_zip_path)
            except KeyError:
                warnings.append(_warning("missing_document", f"Không tìm thấy file EPUB: {href}"))
                continue
            text = _html_to_text(content)
            stylesheet_rules = self._stylesheet_pagination_rules_for_epub_document(epub, source_zip_path, content)
            html = _html_to_sanitized_html(content, stylesheet_rules)
            if self._should_filter_document(source_path, text):
                reason = f"Bỏ qua trang rác: {source_path}"
                warnings.append(_warning("filtered_garbage", reason))
                if any(marker in _normalized_identifier(source_path) for marker in SUSPECT_DOCUMENT_MARKERS):
                    warnings.append(_warning("suspect_chapter", f"Nghi ngờ trang rác: {source_path}"))
                if len(text) < TOO_SHORT_CHAPTER_CHARS:
                    warnings.append(_warning("short_chapter", f"Chương quá ngắn: {source_path}"))
                continue
            if split_mode == "single":
                if text:
                    single_mode_parts.append(text)
                continue

            split_chapters = _split_by_headings(text, source_path=source_path)
            if len(split_chapters) > 1:
                used_heading_split = True
                for chapter in split_chapters:
                    warnings.extend(self._chapter_warnings(chapter))
                    chapters.append(chapter)
                continue
            parsed_chapter = _chapter_from_text(
                text,
                len(chapters) + 1,
                source_path,
                source_path,
                html=html,
                html_source_path=source_zip_path,
            )
            if parsed_chapter:
                warnings.extend(self._chapter_warnings(parsed_chapter))
                chapters.append(parsed_chapter)

        if split_mode == "single":
            combined_text = "\n\n".join(single_mode_parts).strip()
            if combined_text:
                chapters = [ParsedEbookChapter(1, "Toàn bộ ebook", combined_text, "single")]
            return chapters, warnings, "single"

        return chapters, warnings, "heading" if used_heading_split else "spine"

    def _extract_toc_entries(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
        spine_toc_id: str,
    ) -> list[EpubTocEntry]:
        nav_entries = self._extract_nav_toc_entries(epub, rootfile, manifest)
        if nav_entries:
            return nav_entries
        return self._extract_ncx_toc_entries(epub, rootfile, manifest, spine_toc_id)

    def _extract_nav_toc_entries(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
    ) -> list[EpubTocEntry]:
        nav_item = next((item for item in manifest.values() if "nav" in item.properties.split()), None)
        if not nav_item:
            return []
        try:
            nav_root = ET.fromstring(epub.read(_join_zip_path(rootfile, nav_item.href)))
        except (KeyError, ET.ParseError):
            return []

        nav_elements = [element for element in nav_root.iter() if element.tag.split("}")[-1] == "nav"]
        toc_navs = [
            element
            for element in nav_elements
            if "toc" in _normalized_identifier(_local_attr(element, "type"))
        ]
        selected_navs = toc_navs or nav_elements
        if not selected_navs:
            return []

        entries: list[EpubTocEntry] = []
        for element in selected_navs[0].iter():
            if element.tag.split("}")[-1] != "a":
                continue
            href = _local_attr(element, "href")
            if not href:
                continue
            href_without_fragment, fragment = _split_href_fragment(href)
            title = " ".join(part.strip() for part in element.itertext() if part.strip())
            entries.append(EpubTocEntry(title=title, href=href_without_fragment, fragment=fragment, order=len(entries) + 1))
        return entries

    def _extract_ncx_toc_entries(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
        spine_toc_id: str,
    ) -> list[EpubTocEntry]:
        toc_item = manifest.get(spine_toc_id) if spine_toc_id else None
        if toc_item is None:
            toc_item = next(
                (
                    item
                    for item in manifest.values()
                    if item.media_type == "application/x-dtbncx+xml" or item.href.lower().endswith(".ncx")
                ),
                None,
            )
        if toc_item is None:
            return []
        try:
            ncx_root = ET.fromstring(epub.read(_join_zip_path(rootfile, toc_item.href)))
        except (KeyError, ET.ParseError):
            return []

        entries: list[EpubTocEntry] = []
        for nav_point in ncx_root.iter():
            if nav_point.tag.split("}")[-1] != "navPoint":
                continue
            title = ""
            href = ""
            for child in nav_point.iter():
                local_name = child.tag.split("}")[-1]
                if local_name == "text" and child.text and not title:
                    title = child.text.strip()
                if local_name == "content" and not href:
                    href = _local_attr(child, "src")
                if title and href:
                    break
            if not href:
                continue
            href_without_fragment, fragment = _split_href_fragment(href)
            entries.append(EpubTocEntry(title=title, href=href_without_fragment, fragment=fragment, order=len(entries) + 1))
        return entries

    def _chapters_from_toc(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        toc_entries: list[EpubTocEntry],
    ) -> tuple[list[ParsedEbookChapter], list[dict]]:
        chapters: list[ParsedEbookChapter] = []
        warnings: list[dict] = []
        chapter_entries: list[EpubTocEntry] = []
        used_unanchored_sources: set[str] = set()

        for entry in toc_entries:
            identifier = _normalized_identifier(entry.title, entry.href, entry.fragment)
            display_name = entry.title or entry.href
            if any(marker in identifier for marker in GARBAGE_DOCUMENT_MARKERS):
                warnings.append(_warning("filtered_toc_garbage", f"Bỏ qua mục lục rác: {display_name}"))
                continue
            if not entry.fragment:
                source_key = _join_zip_path(rootfile, entry.href)
                if source_key in used_unanchored_sources:
                    warnings.append(_warning("toc_duplicate", f"Bỏ qua mục lục trùng file: {display_name}"))
                    continue
                used_unanchored_sources.add(source_key)
            chapter_entries.append(entry)

        for index, entry in enumerate(chapter_entries):
            source_path = Path(entry.href).stem
            next_entry = chapter_entries[index + 1] if index + 1 < len(chapter_entries) else None
            end_fragment = ""
            if next_entry and next_entry.href == entry.href and entry.fragment:
                end_fragment = next_entry.fragment
            try:
                source_zip_path = _join_zip_path(rootfile, entry.href)
                content = epub.read(source_zip_path)
            except KeyError:
                warnings.append(_warning("toc_unmapped", f"Không tìm thấy chapter từ mục lục: {entry.title or entry.href}"))
                continue

            text = self._html_fragment_to_text(content, entry.fragment, end_fragment)
            stylesheet_rules = self._stylesheet_pagination_rules_for_epub_document(epub, source_zip_path, content)
            html = self._html_fragment_to_html(content, entry.fragment, end_fragment, stylesheet_rules)
            if not text.strip():
                warnings.append(_warning("toc_unmapped", f"Không đọc được chapter từ mục lục: {entry.title or entry.href}"))
                continue
            if self._should_filter_document(source_path, text):
                warnings.append(_warning("filtered_toc_garbage", f"Bỏ qua mục lục rác: {entry.title or entry.href}"))
                continue

            toc_number, toc_title = _parse_heading(entry.title)
            fallback_number = toc_number or len(chapters) + 1
            fallback_title = toc_title or entry.title.strip() or source_path
            chapter = _chapter_from_text(
                text,
                fallback_number,
                fallback_title,
                source_path,
                html=html,
                html_source_path=source_zip_path,
            )
            if not chapter:
                warnings.append(_warning("toc_unmapped", f"Không đọc được chapter từ mục lục: {entry.title or entry.href}"))
                continue
            warnings.extend(self._chapter_warnings(chapter))
            chapters.append(chapter)

        return chapters, warnings

    def _html_fragment_to_text(self, value: bytes, start_fragment: str = "", end_fragment: str = "") -> str:
        if not start_fragment:
            return _html_to_text(value)
        try:
            root = ET.fromstring(value)
        except ET.ParseError:
            return _html_to_text(value)

        body = next((element for element in root.iter() if element.tag.split("}")[-1] == "body"), root)
        children = list(body)
        if not children:
            return _html_to_text(value)

        start_index: int | None = None
        for index, child in enumerate(children):
            if self._element_has_fragment(child, start_fragment):
                start_index = index
                break
        if start_index is None:
            return ""

        end_index = len(children)
        if end_fragment:
            for index in range(start_index + 1, len(children)):
                if self._element_has_fragment(children[index], end_fragment):
                    end_index = index
                    break

        parts = [
            _html_to_text(ET.tostring(child, encoding="utf-8"))
            for child in children[start_index:end_index]
        ]
        return "\n".join(part for part in parts if part).strip()

    def _html_fragment_to_html(
        self,
        value: bytes,
        start_fragment: str = "",
        end_fragment: str = "",
        stylesheet_rules: list[dict] | None = None,
    ) -> str:
        effective_stylesheet_rules = stylesheet_rules
        if effective_stylesheet_rules is None:
            effective_stylesheet_rules = _extract_stylesheet_pagination_rules(value.decode("utf-8", errors="ignore"))
        if not start_fragment:
            return _html_to_sanitized_html(value, effective_stylesheet_rules)
        try:
            root = ET.fromstring(value)
        except ET.ParseError:
            return _html_to_sanitized_html(value, effective_stylesheet_rules)

        body = next((element for element in root.iter() if element.tag.split("}")[-1] == "body"), root)
        children = list(body)
        if not children:
            return _html_to_sanitized_html(value, effective_stylesheet_rules)

        start_index: int | None = None
        for index, child in enumerate(children):
            if self._element_has_fragment(child, start_fragment):
                start_index = index
                break
        if start_index is None:
            return ""

        end_index = len(children)
        if end_fragment:
            for index in range(start_index + 1, len(children)):
                if self._element_has_fragment(children[index], end_fragment):
                    end_index = index
                    break

        parts = [
            _html_to_sanitized_html(ET.tostring(child, encoding="utf-8"), effective_stylesheet_rules)
            for child in children[start_index:end_index]
        ]
        return "\n".join(part for part in parts if part).strip()

    def _element_has_fragment(self, element: ET.Element, fragment: str) -> bool:
        for candidate in element.iter():
            for attr_name, attr_value in candidate.attrib.items():
                if attr_name.split("}")[-1] in {"id", "name"} and str(attr_value) == fragment:
                    return True
        return False

    def _select_cover_item(
        self,
        manifest: dict[str, EpubManifestItem],
        cover_id: str,
    ) -> EpubManifestItem | None:
        if cover_id and cover_id in manifest and manifest[cover_id].media_type.startswith("image/"):
            return manifest[cover_id]

        for item in manifest.values():
            if item.media_type.startswith("image/") and "cover-image" in item.properties.split():
                return item

        for item in manifest.values():
            identifier = _normalized_identifier(item.item_id, item.href)
            if item.media_type.startswith("image/") and any(marker in identifier for marker in ("cover", "front", "titlepage")):
                return item

        return None

    def _extract_cover(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
        cover_id: str,
    ) -> ParsedEbookCover | None:
        cover_item = self._select_cover_item(manifest, cover_id)
        if not cover_item:
            return None
        try:
            content = epub.read(_join_zip_path(rootfile, cover_item.href))
        except KeyError:
            return None
        if not content:
            return None
        return ParsedEbookCover(content=content, href=cover_item.href, media_type=cover_item.media_type)

    def _extract_assets(
        self,
        epub: zipfile.ZipFile,
        rootfile: str,
        manifest: dict[str, EpubManifestItem],
    ) -> dict[str, ParsedEbookAsset]:
        assets: dict[str, ParsedEbookAsset] = {}
        total_size = 0
        for item in manifest.values():
            if not item.media_type.startswith(("audio/", "image/", "video/")):
                continue
            asset_path = _join_zip_path(rootfile, item.href)
            try:
                content = epub.read(asset_path)
            except KeyError:
                continue
            if not content or len(content) > MAX_INLINE_IMAGE_BYTES:
                continue
            if total_size + len(content) > MAX_BOOK_ASSET_BYTES:
                continue
            assets[asset_path] = ParsedEbookAsset(href=item.href, media_type=item.media_type, content=content)
            total_size += len(content)
        return assets

    def _should_filter_document(self, source_path: str, text: str) -> bool:
        identifier = _normalized_identifier(source_path)
        if any(marker in identifier for marker in GARBAGE_DOCUMENT_MARKERS):
            return True
        if "part0000" in identifier and len(text.strip()) < TOO_SHORT_CHAPTER_CHARS:
            return True
        return False

    def _chapter_warnings(self, chapter: ParsedEbookChapter) -> list[dict]:
        warnings: list[dict] = []
        identifier = _normalized_identifier(chapter.source_path, chapter.title)
        if any(marker in identifier for marker in SUSPECT_DOCUMENT_MARKERS):
            warnings.append(_warning("suspect_chapter", f"Nghi ngờ trang rác: {chapter.title}", chapter))
        if len(chapter.text.strip()) < TOO_SHORT_CHAPTER_CHARS:
            warnings.append(_warning("short_chapter", f"Chương quá ngắn: #{chapter.chapter_number} {chapter.title}", chapter))
        return warnings
