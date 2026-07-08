from __future__ import annotations

import time
from pathlib import Path

import pyperclip
from rich.console import Console

from app.config import settings
from app.database.db import add_book, get_book_by_title, add_chapter

console = Console()


def _data_dir() -> Path:
    return settings.resolved_data_dir


def _get_or_create_book(title: str) -> int:
    data_dir = _data_dir()
    db_path = data_dir / "pipeline.db"
    book = get_book_by_title(db_path, title)
    if book:
        return book["id"]
    return add_book(db_path, title)


def _save_raw(text: str, book_title: str, chapter_number: int, chapter_title: str, source_type: str) -> Path:
    data_dir = _data_dir()
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    ts = str(int(time.time()))
    safe_title = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_title)
    raw_path = raw_dir / f"{safe_title}_ch{chapter_number}_{chapter_title}_{ts}.txt"
    raw_path.write_text(text, encoding="utf-8")

    db_path = data_dir / "pipeline.db"
    book_id = _get_or_create_book(book_title)
    add_chapter(db_path, book_id, chapter_number, chapter_title, "", raw_text_path=raw_path)
    return raw_path


def import_clipboard(book_title: str, chapter_number: int, chapter_title: str) -> Path:
    """Import chapter from system clipboard."""
    try:
        text = pyperclip.paste()
    except Exception as exc:
        raise RuntimeError(f"Failed to read clipboard: {exc}") from exc

    if not text.strip():
        raise ValueError("Clipboard is empty or contains only whitespace.")

    raw_path = _save_raw(text, book_title, chapter_number, chapter_title, "clipboard")
    console.print(f"[green]✓ Imported from clipboard: {raw_path}[/green]")
    return raw_path


def import_file(book_title: str, chapter_number: int, chapter_title: str, file_path: Path) -> Path:
    """Import chapter from a local text file."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to read file {file_path}: {exc}") from exc

    if not text.strip():
        raise ValueError(f"File {file_path} is empty or contains only whitespace.")

    raw_path = _save_raw(text, book_title, chapter_number, chapter_title, "file")
    console.print(f"[green]✓ Imported from file: {raw_path}[/green]")
    return raw_path
