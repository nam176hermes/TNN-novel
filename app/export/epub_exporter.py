from __future__ import annotations

import re
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import unquote

from ebooklib import epub

from app.translation.idiom_correction import clean_translation_layout


def _slug(text: str) -> str:
    """Create a filesystem-safe slug from text."""
    return re.sub(r"[^\w\-]", "_", text).strip("_")


def _txt_to_html(text: str, chapter_title: str) -> str:
    """Convert plain Vietnamese text to simple EPUB HTML."""
    lines = text.splitlines()
    escaped_title = escape(chapter_title)
    html_lines: list[str] = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN'",
        "  'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>",
        "<html xmlns='http://www.w3.org/1999/xhtml'>",
        "<head>",
        f"<title>{escaped_title}</title>",
        "<style>",
        "  body { font-family: serif; line-height: 1.6; margin: 5%; }",
        "  h1 { text-align: center; }",
        "  p { margin-bottom: 0.8em; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escaped_title}</h1>",
    ]

    # Group lines into paragraphs (split on blank lines)
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))

    for para in paragraphs:
        # Skip section headers that are just translation artifacts
        if para.upper().startswith("TRANSLATION") or para.upper().startswith("NEW_TERMS"):
            continue
        html_lines.append(f"<p>{escape(para)}</p>")

    html_lines += ["</body>", "</html>"]
    return "\n".join(html_lines)


def _image_media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


def _safe_epub_asset_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).name).strip("._-")
    return safe or "image"


def _data_dir_from_html_path(path: Path) -> Path:
    if path.parent.name == "translated":
        return path.parent.parent
    return path.parent


def _resolve_book_asset_path(content_html_path: Path, src: str) -> Path | None:
    src_value = unquote(src).strip()
    if not src_value.startswith("/book-assets/"):
        return None
    parts = [part for part in src_value.removeprefix("/book-assets/").split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return None
    assets_root = _data_dir_from_html_path(content_html_path) / "book_assets"
    candidate = (assets_root / Path(*parts)).resolve()
    try:
        candidate.relative_to(assets_root.resolve())
    except ValueError:
        return None
    return candidate


def _rich_html_to_epub_html(
    content_html: str,
    chapter_title: str,
    image_resolver,
) -> str:
    escaped_title = escape(chapter_title)

    def replace_src(match: re.Match[str]) -> str:
        epub_src = image_resolver(match.group(2))
        if not epub_src:
            return ""
        return f'{match.group(1)}{epub_src}{match.group(3)}'

    rewritten = re.sub(r'(<img\b[^>]*?\ssrc=")([^"]+)("[^>]*>)', replace_src, content_html, flags=re.IGNORECASE)
    rewritten = re.sub(r"(<img\b[^>]*?)(?<!/)>", r"\1 />", rewritten, flags=re.IGNORECASE)
    return "\n".join(
        [
            "<?xml version='1.0' encoding='utf-8'?>",
            "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN'",
            "  'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>",
            "<html xmlns='http://www.w3.org/1999/xhtml'>",
            "<head>",
            f"<title>{escaped_title}</title>",
            "<link rel='stylesheet' type='text/css' href='style.css'/>",
            "</head>",
            "<body>",
            f"<h1>{escaped_title}</h1>",
            rewritten,
            "</body>",
            "</html>",
        ]
    )


def export_epub(
    book_title: str,
    author: str,
    chapters: list[dict],
    output_path: Path,
    language: str = "vi",
    cover_path: Path | str | None = None,
) -> Path:
    """
    Export translated chapters as an EPUB file.

    Args:
        book_title: Title of the book.
        author: Author name.
        chapters: List of chapter dicts with keys:
            chapter_number, title, translated_text_path
        output_path: Output .epub file path.
        language: Language code for the EPUB (default: 'vi' for Vietnamese).
        cover_path: Optional image path to embed as the EPUB cover.

    Returns:
        Path to the created EPUB file.
    """
    book = epub.EpubBook()
    book.set_identifier(f"{_slug(book_title)}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    book.set_title(book_title)
    book.set_language(language)
    book.add_author(author or "Unknown")

    if cover_path and Path(cover_path).exists():
        cover_file = Path(cover_path)
        book.set_cover(cover_file.name, cover_file.read_bytes())

    # Default CSS
    css_content = """
    body { font-family: serif; line-height: 1.6; margin: 5%; }
    h1 { text-align: center; font-size: 1.5em; margin-bottom: 1em; }
    p { margin-bottom: 0.8em; text-indent: 1em; }
    """
    nav_css = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=css_content,
    )
    book.add_item(nav_css)

    epub_chapters: list[epub.EpubHtml] = []
    spine = ["nav"]
    toc = []
    embedded_images: dict[Path, str] = {}
    used_image_names: set[str] = set()

    def register_image(content_html_path: Path, src: str) -> str:
        image_path = _resolve_book_asset_path(content_html_path, src)
        if image_path is None or not image_path.exists() or not image_path.is_file():
            return ""
        image_path = image_path.resolve()
        if image_path not in embedded_images:
            base_name = _safe_epub_asset_name(image_path.name)
            asset_name = base_name
            counter = 1
            while asset_name in used_image_names:
                counter += 1
                asset_name = f"{Path(base_name).stem}_{counter}{Path(base_name).suffix}"
            used_image_names.add(asset_name)
            epub_name = f"images/{asset_name}"
            book.add_item(
                epub.EpubItem(
                    uid=f"img_{len(embedded_images) + 1}",
                    file_name=epub_name,
                    media_type=_image_media_type(image_path),
                    content=image_path.read_bytes(),
                )
            )
            embedded_images[image_path] = epub_name
        return embedded_images[image_path]

    # Sort by chapter number
    sorted_chapters = sorted(chapters, key=lambda c: c.get("chapter_number", 0))

    for ch in sorted_chapters:
        ch_num = ch.get("chapter_number", 0)
        ch_title = ch.get("title") or f"Chương {ch_num}"
        trans_path = ch.get("translated_text_path")
        content_html_path = ch.get("content_html_path")

        if not trans_path or not Path(trans_path).exists():
            continue

        text = clean_translation_layout(Path(trans_path).read_text(encoding="utf-8"))
        if content_html_path and Path(content_html_path).exists():
            html_path = Path(content_html_path)
            content_html = html_path.read_text(encoding="utf-8")
            html_content = _rich_html_to_epub_html(
                content_html,
                ch_title,
                lambda src, html_path=html_path: register_image(html_path, src),
            )
        else:
            html_content = _txt_to_html(text, ch_title)

        epub_ch = epub.EpubHtml(
            title=ch_title,
            file_name=f"chapter_{ch_num:04d}.xhtml",
            lang=language,
        )
        epub_ch.content = html_content.encode("utf-8")
        epub_ch.add_item(nav_css)

        book.add_item(epub_ch)
        epub_chapters.append(epub_ch)
        spine.append(epub_ch)
        toc.append(epub.Link(f"chapter_{ch_num:04d}.xhtml", ch_title, f"ch{ch_num}"))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})

    return output_path
