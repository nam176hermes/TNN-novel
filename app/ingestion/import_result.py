from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterImportResult(Mapping[str, object]):
    """Typed, compatibility-preserving metadata for one stored chapter import."""

    book_id: int
    chapter_id: int
    stored_text_length: int
    content_hash: str
    operation: str
    warnings: tuple[str, ...] = ()
    title: str = ""
    chapter_number: int = 0
    chapter_title: str = ""
    source_type: str = ""
    source_url: str = ""
    adapter_id: str = ""
    path: str = ""
    fetch_method: str = ""
    fetch_attempts: int = 0
    fetch_elapsed_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "book_id": self.book_id,
            "chapter_id": self.chapter_id,
            "stored_text_length": self.stored_text_length,
            "content_hash": self.content_hash,
            "operation": self.operation,
            "warnings": list(self.warnings),
            "title": self.title,
            "chapter_number": self.chapter_number,
            "chapter_title": self.chapter_title,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "adapter_id": self.adapter_id,
            "path": self.path,
            "fetch_method": self.fetch_method,
            "fetch_attempts": self.fetch_attempts,
            "fetch_elapsed_ms": self.fetch_elapsed_ms,
        }

    def __getitem__(self, key: str) -> object:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())
