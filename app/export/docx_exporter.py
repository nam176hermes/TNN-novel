from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from app.translation.idiom_correction import clean_translation_layout


def _paragraph(text: str, style: str = "") -> str:
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    escaped = escape(text)
    return (
        "<w:p>"
        f"{style_xml}"
        "<w:r>"
        f'<w:t xml:space="preserve">{escaped}</w:t>'
        "</w:r>"
        "</w:p>"
    )


def _chapter_paragraphs(title: str, text: str) -> list[str]:
    paragraphs = [_paragraph(title, "Heading1")]
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            current.append(stripped)
            continue
        if current:
            paragraphs.append(_paragraph(" ".join(current)))
            current = []
    if current:
        paragraphs.append(_paragraph(" ".join(current)))
    return paragraphs


def export_docx(
    book_title: str,
    author: str,
    chapters: list[dict],
    output_path: Path,
) -> Path:
    """Export translated chapters as a minimal Word-compatible DOCX file."""
    document_parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
        "<w:body>",
        _paragraph(book_title, "Title"),
    ]
    if author:
        document_parts.append(_paragraph(author, "Subtitle"))

    for chapter in sorted(chapters, key=lambda item: item.get("chapter_number", 0)):
        translated_path = chapter.get("translated_text_path")
        if not translated_path or not Path(translated_path).exists():
            continue
        number = chapter.get("chapter_number", 0)
        title = chapter.get("title") or f"Chương {number}"
        text = clean_translation_layout(Path(translated_path).read_text(encoding="utf-8"))
        document_parts.extend(_chapter_paragraphs(f"Chương {number}: {title}", text))

    document_parts.append(
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" '
        'w:bottom="1440" w:left="1440"/></w:sectPr>'
    )
    document_parts.extend(["</w:body>", "</w:document>"])

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
</w:styles>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        archive.writestr("word/document.xml", "\n".join(document_parts))
        archive.writestr("word/styles.xml", styles_xml)

    return output_path
