from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from app.export.docx_exporter import export_docx
from app.export.epub_exporter import export_epub
from app.export.m4b_exporter import export_m4b
from app.export.text_exporter import export_txt
from app.mobile_api.services.pipeline_service import PipelineService


EXPORT_FORMATS = {"txt", "docx", "epub"}
AUDIOBOOK_EXPORT_FORMATS = {"m4b"}
ANNOTATION_EXPORT_FORMATS = {"json", "md", "csv"}
ANNOTATION_EXPORT_KINDS = {"bookmark", "highlight", "note"}
ANNOTATION_EXPORT_KIND_LABELS = {
    "bookmark": "bookmarks",
    "highlight": "highlights",
    "note": "notes",
}
EXPORT_MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
}
AUDIOBOOK_EXPORT_MEDIA_TYPES = {
    "m4b": "audio/mp4",
}
ANNOTATION_EXPORT_MEDIA_TYPES = {
    "json": "application/json; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}


class ExportService:
    def __init__(self, pipeline: PipelineService):
        self.pipeline = pipeline

    @staticmethod
    def _safe_filename_part(value: str) -> str:
        safe = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in value)
        safe = "_".join(part for part in safe.split("_") if part)
        return safe or "book"

    def translated_chapters(self, book_id: int) -> list[dict]:
        chapters = self.pipeline.list_chapters(book_id)
        return [
            chapter
            for chapter in chapters
            if chapter.get("translated_text_path") and Path(chapter["translated_text_path"]).exists()
        ]

    def audio_chapters(self, book_id: int) -> list[dict]:
        chapters = self.pipeline.list_chapters(book_id)
        return [
            chapter
            for chapter in chapters
            if chapter.get("audio_path") and Path(chapter["audio_path"]).exists()
        ]

    @staticmethod
    def _empty_annotation_kind_counts() -> dict[str, int]:
        return {kind: 0 for kind in sorted(ANNOTATION_EXPORT_KINDS)}

    def _annotation_kind_counts(self, annotations: list[dict]) -> dict[str, int]:
        counts = self._empty_annotation_kind_counts()
        for annotation in annotations:
            kind = str(annotation.get("kind") or "").casefold()
            if kind in counts:
                counts[kind] += 1
        return counts

    def _annotation_chapter_groups(self, annotations: list[dict]) -> list[dict]:
        groups: dict[tuple[int, int, str], dict] = {}
        for annotation in annotations:
            chapter_id = int(annotation.get("chapter_id") or 0)
            chapter_number = int(annotation.get("chapter_number") or 0)
            chapter_title = str(annotation.get("chapter_title") or "")
            key = (chapter_number, chapter_id, chapter_title)
            group = groups.setdefault(
                key,
                {
                    "chapter_id": chapter_id,
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title,
                    "annotation_count": 0,
                    "kind_counts": self._empty_annotation_kind_counts(),
                    "annotation_ids": [],
                    "client_ids": [],
                },
            )
            group["annotation_count"] += 1
            kind = str(annotation.get("kind") or "").casefold()
            if kind in group["kind_counts"]:
                group["kind_counts"][kind] += 1
            annotation_id = annotation.get("id")
            if annotation_id is not None:
                group["annotation_ids"].append(int(annotation_id))
            client_id = str(annotation.get("client_id") or "").strip()
            if client_id:
                group["client_ids"].append(client_id)

        return [
            groups[key]
            for key in sorted(groups)
        ]

    def _annotation_export_payload(self, book: dict, annotations: list[dict], kinds: set[str]) -> dict:
        chapters = self._annotation_chapter_groups(annotations)
        return {
            "format": "novel_tnn_reader_annotations",
            "version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "scope": {
                "kinds": sorted(kinds),
                "label": self._annotation_export_scope(kinds),
            },
            "book": {
                "id": book["id"],
                "title": book["title"],
                "author": book.get("author") or "",
            },
            "annotation_count": len(annotations),
            "kind_counts": self._annotation_kind_counts(annotations),
            "chapter_count": len(chapters),
            "chapters": chapters,
            "annotations": annotations,
        }

    @staticmethod
    def _annotation_markdown(book: dict, annotations: list[dict]) -> str:
        lines = [
            f"# {book['title']} - Reader annotations",
            "",
        ]
        if book.get("author"):
            lines.extend([f"Author: {book['author']}", ""])
        if not annotations:
            lines.append("_No active annotations._")
            return "\n".join(lines).rstrip() + "\n"

        for annotation in annotations:
            chapter_number = annotation.get("chapter_number") or 0
            chapter_title = annotation.get("chapter_title") or ""
            kind = annotation.get("kind") or "annotation"
            lines.extend(
                [
                    f"## Chapter {chapter_number}: {chapter_title}",
                    "",
                    f"- Type: {kind}",
                    f"- Paragraph: {annotation.get('paragraph_index', 0)}",
                ]
            )
            client_id = (annotation.get("client_id") or "").strip()
            if client_id:
                lines.append(f"- Client ID: {client_id}")
            selected_text = (annotation.get("selected_text") or "").strip()
            note = (annotation.get("note") or "").strip()
            if selected_text:
                lines.extend(["", "> " + selected_text.replace("\n", "\n> ")])
            if note:
                lines.extend(["", note])
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _write_annotation_csv(path: Path, annotations: list[dict]) -> None:
        fieldnames = [
            "id",
            "client_id",
            "kind",
            "chapter_number",
            "chapter_title",
            "paragraph_index",
            "char_start",
            "char_end",
            "selected_text",
            "note",
            "color",
            "created_at",
            "updated_at",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for annotation in annotations:
                writer.writerow({field: annotation.get(field, "") for field in fieldnames})

    @staticmethod
    def _annotation_kind_filter(kind: str | None) -> set[str]:
        if not kind:
            return set()
        kinds = {item.strip().casefold() for item in kind.split(",") if item.strip()}
        unsupported = sorted(kinds - ANNOTATION_EXPORT_KINDS)
        if unsupported:
            raise ValueError(f"Unsupported annotation kind: {', '.join(unsupported)}")
        return kinds

    @staticmethod
    def _annotation_export_scope(kinds: set[str]) -> str:
        if not kinds:
            return "annotations"
        if len(kinds) == 1:
            return ANNOTATION_EXPORT_KIND_LABELS[next(iter(kinds))]
        return "annotations_" + "_".join(ANNOTATION_EXPORT_KIND_LABELS[kind] for kind in sorted(kinds))

    def export_book(self, book_id: int, format: str) -> dict:
        export_format = format.casefold()
        if export_format not in EXPORT_FORMATS:
            raise ValueError(f"Unsupported export format: {format}")

        book = self.pipeline.get_book(book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        chapters = self.translated_chapters(book_id)
        if not chapters:
            raise ValueError("No translated chapters to export")

        safe_title = self._safe_filename_part(book["title"])
        if safe_title == "book":
            safe_title = f"book_{book_id}"
        output_dir = self.pipeline.data_dir / "exports" / safe_title
        output_path = output_dir / f"{safe_title}.{export_format}"

        if export_format == "txt":
            export_txt(book["title"], book.get("author", ""), chapters, output_path)
        elif export_format == "docx":
            export_docx(book["title"], book.get("author", ""), chapters, output_path)
        else:
            export_epub(
                book["title"],
                book.get("author", ""),
                chapters,
                output_path,
                cover_path=book.get("cover_path") or None,
            )

        size_bytes = output_path.stat().st_size
        return {
            "book_id": book_id,
            "book_title": book["title"],
            "format": export_format,
            "filename": output_path.name,
            "path": str(output_path),
            "media_type": EXPORT_MEDIA_TYPES[export_format],
            "size_bytes": size_bytes,
            "chapter_count": len(chapters),
        }

    def export_audiobook(self, book_id: int, format: str) -> dict:
        export_format = format.casefold()
        if export_format not in AUDIOBOOK_EXPORT_FORMATS:
            raise ValueError(f"Unsupported audiobook export format: {format}")

        book = self.pipeline.get_book(book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        chapters = self.audio_chapters(book_id)
        if not chapters:
            raise ValueError("No chapter audio files found. Run TTS first.")

        safe_title = self._safe_filename_part(book["title"])
        if safe_title == "book":
            safe_title = f"book_{book_id}"
        output_dir = self.pipeline.data_dir / "exports" / safe_title
        output_path = output_dir / f"{safe_title}.{export_format}"

        export_m4b(book["title"], book.get("author", ""), chapters, output_path)

        size_bytes = output_path.stat().st_size
        return {
            "book_id": book_id,
            "book_title": book["title"],
            "format": export_format,
            "filename": output_path.name,
            "path": str(output_path),
            "media_type": AUDIOBOOK_EXPORT_MEDIA_TYPES[export_format],
            "size_bytes": size_bytes,
            "chapter_count": len(chapters),
        }

    def export_annotations(self, book_id: int, format: str, *, kind: str | None = None) -> dict:
        export_format = format.casefold()
        if export_format not in ANNOTATION_EXPORT_FORMATS:
            raise ValueError(f"Unsupported annotation export format: {format}")
        kinds = self._annotation_kind_filter(kind)

        book = self.pipeline.get_book(book_id)
        if not book:
            raise ValueError(f"Book {book_id} not found")
        annotations = self.pipeline.list_reader_annotations(book_id)
        if annotations is None:
            raise ValueError(f"Book {book_id} not found")
        if kinds:
            annotations = [annotation for annotation in annotations if str(annotation.get("kind") or "").casefold() in kinds]

        safe_title = self._safe_filename_part(book["title"])
        if safe_title == "book":
            safe_title = f"book_{book_id}"
        output_dir = self.pipeline.data_dir / "exports" / safe_title
        output_dir.mkdir(parents=True, exist_ok=True)
        scope = self._annotation_export_scope(kinds)
        output_path = output_dir / f"{safe_title}.{scope}.{export_format}"

        if export_format == "json":
            payload = self._annotation_export_payload(book, annotations, kinds)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        elif export_format == "md":
            output_path.write_text(self._annotation_markdown(book, annotations), encoding="utf-8")
        else:
            self._write_annotation_csv(output_path, annotations)

        size_bytes = output_path.stat().st_size
        return {
            "book_id": book_id,
            "book_title": book["title"],
            "format": export_format,
            "filename": output_path.name,
            "path": str(output_path),
            "media_type": ANNOTATION_EXPORT_MEDIA_TYPES[export_format],
            "size_bytes": size_bytes,
            "chapter_count": 0,
            "annotation_count": len(annotations),
            "annotation_kinds": sorted(kinds),
        }
