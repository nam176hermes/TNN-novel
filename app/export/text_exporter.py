from __future__ import annotations

from pathlib import Path

from app.translation.idiom_correction import clean_translation_layout


def export_txt(
    book_title: str,
    author: str,
    chapters: list[dict],
    output_path: Path,
) -> Path:
    """Export translated chapters as a single UTF-8 text file."""
    lines = [book_title]
    if author:
        lines.append(author)
    lines.append("")

    for chapter in sorted(chapters, key=lambda item: item.get("chapter_number", 0)):
        translated_path = chapter.get("translated_text_path")
        if not translated_path or not Path(translated_path).exists():
            continue
        number = chapter.get("chapter_number", 0)
        title = chapter.get("title") or f"Chương {number}"
        text = clean_translation_layout(Path(translated_path).read_text(encoding="utf-8")).strip()
        lines.extend([f"Chương {number}: {title}", "", text, ""])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return output_path
