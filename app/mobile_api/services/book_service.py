"""Book metadata, covers and artifact cleanup behind the compatibility pipeline."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from app.database.book_repository import (
    add_book,
    delete_book as db_delete_book,
    get_book_by_id,
    get_book_by_title,
    list_books_with_active_chapters,
    list_translated_book_summaries as db_list_translated_book_summaries,
    update_book as db_update_book,
)
from app.database.chapter_repository import list_chapters
from app.mobile_api.services.content_file_service import ContentFileService
from app.storage.artifact_paths import ArtifactClass, ArtifactPathError

BOOK_COVER_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

BOOK_COVER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

MAX_BOOK_COVER_BYTES = 10 * 1024 * 1024


class BookService:
    def __init__(self, *, data_dir: Path, db_path: Path, content_files: ContentFileService):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.content_files = content_files

    @staticmethod
    def _unlink_path(value: str | None) -> None:
        if not value:
            return
        Path(value).unlink(missing_ok=True)

    def _cover_url(self, cover_path: str | None) -> str:
        if not cover_path:
            return ""
        covers_dir = self.data_dir / "covers"
        try:
            path = self.content_files.resolve_artifact_file(cover_path, ArtifactClass.COVER)
        except ArtifactPathError:
            return ""
        try:
            relative_path = path.relative_to(covers_dir)
        except ValueError:
            return ""
        return f"/covers/{relative_path.as_posix()}"

    def _book_cover_extension(self, filename: str, content_type: str) -> str:
        normalized_type = content_type.lower().split(";", 1)[0].strip()
        if normalized_type in BOOK_COVER_CONTENT_TYPES:
            return BOOK_COVER_CONTENT_TYPES[normalized_type]

        suffix = Path(filename).suffix.lower()
        if suffix in BOOK_COVER_SUFFIXES:
            return ".jpg" if suffix == ".jpeg" else suffix
        raise ValueError("Unsupported cover image format")

    def _safe_book_cover_stem(self, title: str, book_id: int) -> str:
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._-")
        return safe_title or f"book_{book_id}"

    def _book_payload(self, book: dict | None) -> dict | None:
        if not book:
            return None
        payload = dict(book)
        payload["cover_url"] = self._cover_url(payload.get("cover_path"))
        return payload

    def _book_id_for_title(self, title: str) -> int:
        if not title.strip():
            raise ValueError("Book title is required")
        book = get_book_by_title(self.db_path, title)
        return book["id"] if book else self.create_book(title)

    def _book_id_for_import(
        self,
        title: str,
        *,
        author: str = "",
        source: str = "manual",
        source_url: str = "",
    ) -> int:
        if not title.strip():
            raise ValueError("Book title is required")

        book = get_book_by_title(self.db_path, title)
        if not book:
            return self.create_book(title, author=author, source=source, source_url=source_url)

        updates: dict[str, str] = {}
        if author and not book.get("author"):
            updates["author"] = author
        if source and (not book.get("source") or book.get("source") == "manual"):
            updates["source"] = source
        if source_url and not book.get("source_url"):
            updates["source_url"] = source_url
        if updates:
            self.update_book(book["id"], **updates)
        return book["id"]

    def list_books(self) -> list[dict]:
        return [
            self._book_payload(book)
            for book in list_books_with_active_chapters(self.db_path)
        ]

    def list_translated_book_summaries(self) -> list[dict]:
        summaries = db_list_translated_book_summaries(self.db_path)
        for summary in summaries:
            summary["cover_url"] = self._cover_url(summary.get("cover_path"))
        return summaries

    def get_book(self, book_id: int) -> dict | None:
        return self._book_payload(get_book_by_id(self.db_path, book_id))

    def create_book(
        self,
        title: str,
        author: str = "",
        source: str = "manual",
        source_url: str = "",
        cover_path: str = "",
    ) -> int:
        return add_book(self.db_path, title, author, source, source_url, cover_path)

    def update_book(self, book_id: int, **kwargs) -> dict | None:
        updated = db_update_book(
            self.db_path,
            book_id,
            title=kwargs.get("title"),
            author=kwargs.get("author"),
            source=kwargs.get("source"),
            source_url=kwargs.get("source_url"),
            cover_path=kwargs.get("cover_path"),
        )
        if not updated:
            return None
        if kwargs.get("title"):
            return self._book_payload(get_book_by_title(self.db_path, kwargs["title"]))
        return self._book_payload(get_book_by_id(self.db_path, book_id))

    def update_book_cover(
        self,
        book_id: int,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict | None:
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            return None
        if not content:
            raise ValueError("Cover image is empty")
        if len(content) > MAX_BOOK_COVER_BYTES:
            raise ValueError("Cover image is too large")

        extension = self._book_cover_extension(filename, content_type)
        covers_dir = self.data_dir / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = self._safe_book_cover_stem(str(book.get("title") or ""), book_id)
        cover_path = covers_dir / f"{safe_stem}_{book_id}_{time.time_ns()}{extension}"
        cover_path.write_bytes(content)
        return self.update_book(book_id, cover_path=str(cover_path))

    def delete_book(self, book_id: int) -> bool:
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            return False

        chapters = list_chapters(self.db_path, book_id)
        file_paths = [book.get("cover_path")]
        for chapter in chapters:
            file_paths.extend(
                chapter.get(key)
                for key in ("raw_text_path", "cleaned_text_path", "translated_text_path", "content_html_path", "audio_path")
            )

        if not db_delete_book(self.db_path, book_id):
            return False

        for file_path in file_paths:
            self._unlink_path(file_path)
        shutil.rmtree(self.data_dir / "book_assets" / str(book_id), ignore_errors=True)
        return True
