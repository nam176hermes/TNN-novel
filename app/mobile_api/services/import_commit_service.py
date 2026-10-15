"""Reviewed import storage, revalidation, rollback and post-import follow-ups."""
from __future__ import annotations

import logging
import shutil
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import get_connection
from app.database.book_repository import (
    find_import_book_with_connection,
    get_book_by_title,
    resolve_import_book_with_connection,
)
from app.database.import_repository import (
    add_chapter,
    canonicalize_import_url,
    insert_import_chapter_with_connection,
    list_active_import_chapters_with_connection,
    update_import_chapter_with_connection,
    upsert_import_chapter_with_connection,
)
from app.ingestion.import_metadata import detect_import_metadata, normalize_import_text, source_hash
from app.ingestion.import_result import ChapterImportResult
from app.ingestion.source_adapters import FetchErrorCode, SourceAdapterError
from app.mobile_api.services.book_service import BookService
from app.mobile_api.services.content_file_service import ContentFileService
from app.storage.chapter_content import write_versioned_text

logger = logging.getLogger(__name__)


class ImportCommitService:
    def __init__(self, *, data_dir: Path, db_path: Path, books: BookService, content_files: ContentFileService):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.books = books
        self.content_files = content_files

    @staticmethod
    def _safe_filename_part(value: str) -> str:
        return "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in value)

    def import_from_text(
        self,
        title: str,
        chapter_number: int,
        chapter_title: str,
        text: str,
        source_type: str = "paste",
        source_url: str = "",
        author: str = "",
        book_source: str = "manual",
        book_source_url: str = "",
        adapter_id: str = "",
    ) -> ChapterImportResult:
        normalized_text = normalize_import_text(text)
        if not normalized_text:
            raise SourceAdapterError(
                "Chapter content is empty",
                code=FetchErrorCode.CONTENT_INVALID,
                retryable=False,
                http_status=422,
            )
        metadata = detect_import_metadata(
            title=title,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            text=normalized_text,
        )
        detected_title = metadata["title"]
        detected_chapter_number = metadata["chapter_number"]
        detected_chapter_title = metadata["chapter_title"]
        try:
            canonical_chapter_url = canonicalize_import_url(source_url)
            canonical_source_url = canonicalize_import_url(book_source_url or source_url)
        except Exception as exc:
            code_value = str(getattr(exc, "code", FetchErrorCode.INVALID_URL.value))
            try:
                code = FetchErrorCode(code_value)
            except ValueError:
                code = FetchErrorCode.INVALID_URL
            raise SourceAdapterError(
                "Source URL is invalid for import",
                code=code,
                retryable=False,
                http_status=400,
            ) from exc

        safe_title = self._safe_filename_part(detected_title) or "book"
        safe_chapter_title = self._safe_filename_part(detected_chapter_title) or "chapter"
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{safe_title}_ch{detected_chapter_number}_{safe_chapter_title}_{time.time_ns()}.txt"
        try:
            raw_path.write_text(normalized_text, encoding="utf-8")
            stored_text = raw_path.read_text(encoding="utf-8")
        except OSError as exc:
            raw_path.unlink(missing_ok=True)
            raise SourceAdapterError(
                "Could not store chapter content",
                code=FetchErrorCode.IMPORT_FAILED,
                retryable=False,
                http_status=500,
            ) from exc
        try:
            with get_connection(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                book = resolve_import_book_with_connection(
                    conn,
                    title=detected_title,
                    author=author,
                    source=book_source,
                    source_url=book_source_url or source_url,
                    canonical_source_url=canonical_source_url,
                )
                book_id = int(book["id"])
                upserted = upsert_import_chapter_with_connection(
                    conn,
                    book_id=book_id,
                    chapter_number=detected_chapter_number,
                    title=detected_chapter_title,
                    source_url=source_url,
                    canonical_chapter_url=canonical_chapter_url,
                    adapter_id=adapter_id,
                    raw_text_path=raw_path,
                    content_hash=metadata["source_hash"],
                    source_updated_at=datetime.now(timezone.utc).isoformat(),
                )
                conn.commit()
        except ValueError as exc:
            raw_path.unlink(missing_ok=True)
            if "Duplicate" in str(exc):
                raise SourceAdapterError(
                    str(exc),
                    code=FetchErrorCode.DUPLICATE,
                    retryable=False,
                    http_status=409,
                ) from exc
            raise SourceAdapterError(
                "Could not import chapter content",
                code=FetchErrorCode.IMPORT_FAILED,
                retryable=False,
                http_status=500,
            ) from exc
        except Exception as exc:
            raw_path.unlink(missing_ok=True)
            raise SourceAdapterError(
                "Could not import chapter content",
                code=FetchErrorCode.IMPORT_FAILED,
                retryable=False,
                http_status=500,
            ) from exc
        chapter_id = upserted.chapter_id
        operation = upserted.operation
        if operation == "skipped_duplicate":
            raw_path.unlink(missing_ok=True)
            result_path = upserted.raw_text_path
        else:
            result_path = str(raw_path)
        return ChapterImportResult(
            book_id=book_id,
            chapter_id=chapter_id,
            stored_text_length=len(stored_text),
            content_hash=source_hash(stored_text),
            operation=operation,
            title=detected_title,
            chapter_number=detected_chapter_number,
            chapter_title=detected_chapter_title,
            source_type=source_type,
            source_url=source_url,
            adapter_id=adapter_id,
            path=result_path,
        )

    def _write_import_text_file(
        self,
        *,
        book_title: str,
        chapter_number: int,
        chapter_title: str,
        text: str,
        content_kind: str,
    ) -> Path:
        safe_title = self._safe_filename_part(book_title) or "book"
        safe_chapter_title = self._safe_filename_part(chapter_title) or "chapter"
        directory = self.data_dir / ("translated" if content_kind == "translated" else "raw")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_title}_ch{chapter_number}_{safe_chapter_title}_{time.time_ns()}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _prepare_reviewed_import_items(
        self,
        *,
        chapters: list[dict],
        content_kind: str,
    ) -> list[dict]:
        prepared: list[dict] = []
        for item in chapters:
            chapter_number = int(item.get("chapter_number") or 0)
            chapter_title = str(item.get("chapter_title") or "").strip() or f"Chương {chapter_number}"
            if chapter_number <= 0:
                raise ValueError("Chapter number must be positive")

            raw_text = str(item.get("raw_text") or "")
            translated_text = str(item.get("translated_text") or "")
            text = str(item.get("text") or "")
            if content_kind == "raw":
                raw_text = raw_text or text
            elif content_kind == "translated":
                translated_text = translated_text or text
            else:
                raw_text = raw_text or text

            raw_text = raw_text.strip()
            translated_text = translated_text.strip()
            if not raw_text and not translated_text:
                raise ValueError(f"Chapter {chapter_number} text is empty")
            prepared.append(
                {
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title,
                    "raw_text": raw_text,
                    "translated_text": translated_text,
                }
            )
        return prepared

    @staticmethod
    def _import_chapter_fingerprint(chapter: dict) -> tuple:
        return (
            int(chapter.get("id") or 0),
            int(chapter.get("chapter_number") or 0),
            str(chapter.get("title") or ""),
            str(chapter.get("raw_text_path") or ""),
            str(chapter.get("translated_text_path") or ""),
            str(chapter.get("source_hash") or ""),
            str(chapter.get("status") or ""),
            str(chapter.get("translated_at") or ""),
            str(chapter.get("deleted_at") or ""),
        )

    def _classify_reviewed_import_items(
        self,
        *,
        prepared: list[dict],
        existing_chapters: list[dict],
        duplicate_strategy: str,
        book_id: int | None,
    ) -> list[dict]:
        by_number = {int(chapter["chapter_number"]): dict(chapter) for chapter in existing_chapters}
        by_source_hash = {
            str(chapter.get("source_hash") or ""): dict(chapter)
            for chapter in existing_chapters
            if str(chapter.get("source_hash") or "")
        }
        classified: list[dict] = []

        for item in prepared:
            planned = dict(item)
            chapter_number = int(planned["chapter_number"])
            source_hash = str(planned["source_hash"])
            existing = by_number.get(chapter_number)
            source_duplicate = by_source_hash.get(source_hash)
            if source_duplicate and int(source_duplicate["chapter_number"]) != chapter_number:
                raise ValueError(
                    f"Duplicate chapter content for chapter {chapter_number} in book {book_id or 'new'}"
                )

            if existing:
                if duplicate_strategy == "error":
                    raise ValueError(f"Duplicate chapter number {chapter_number} for book {book_id or 'new'}")
                planned["action"] = "SKIP" if duplicate_strategy == "skip" else "REPLACE"
                planned["existing_id"] = int(existing.get("id") or 0)
                planned["existing_fingerprint"] = self._import_chapter_fingerprint(existing)
            else:
                planned["action"] = "ADD"
                planned["existing_id"] = 0
                planned["existing_fingerprint"] = None

            classified.append(planned)
            if planned["action"] != "SKIP":
                synthetic = {
                    "id": planned["existing_id"],
                    "chapter_number": chapter_number,
                    "title": planned["chapter_title"],
                    "raw_text_path": existing.get("raw_text_path") if existing else "",
                    "translated_text_path": existing.get("translated_text_path") if existing else "",
                    "source_hash": source_hash,
                    "status": "translated" if planned["translated_text"] else "imported",
                    "translated_at": existing.get("translated_at") if existing else "",
                    "deleted_at": "",
                }
                by_number[chapter_number] = synthetic
                by_source_hash[source_hash] = synthetic
        return classified

    def _stage_reviewed_import_files(self, *, plan: list[dict], book_title: str) -> tuple[Path, list[dict]]:
        staging_dir = self.data_dir / ".import-staging" / uuid.uuid4().hex
        staged: list[dict] = []
        try:
            for index, item in enumerate(plan):
                if item["action"] == "SKIP":
                    continue
                entry = dict(item)
                for content_kind in ("raw", "translated"):
                    text = str(item[f"{content_kind}_text"] or "")
                    if not text:
                        entry[f"{content_kind}_staged_path"] = None
                        entry[f"{content_kind}_final_path"] = None
                        continue
                    safe_title = self._safe_filename_part(book_title) or "book"
                    safe_chapter_title = self._safe_filename_part(item["chapter_title"]) or "chapter"
                    filename = (
                        f"{safe_title}_ch{item['chapter_number']}_{safe_chapter_title}_"
                        f"{uuid.uuid4().hex}.txt"
                    )
                    staged_path = staging_dir / f"{index}_{content_kind}.txt"
                    final_path = self.data_dir / content_kind / filename
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    staged_path.write_text(text, encoding="utf-8")
                    entry[f"{content_kind}_staged_path"] = staged_path
                    entry[f"{content_kind}_final_path"] = final_path
                staged.append(entry)
            return staging_dir, staged
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    @staticmethod
    def _finalize_reviewed_import_files(plan: list[dict]) -> list[Path]:
        finalized: list[Path] = []
        try:
            for item in plan:
                for content_kind in ("raw", "translated"):
                    staged_path = item.get(f"{content_kind}_staged_path")
                    final_path = item.get(f"{content_kind}_final_path")
                    if not staged_path or not final_path:
                        continue
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    staged_path.replace(final_path)
                    finalized.append(final_path)
            return finalized
        except Exception:
            for path in finalized:
                path.unlink(missing_ok=True)
            raise

    def import_reviewed_text_plan(
        self,
        *,
        title: str,
        chapters: list[dict],
        content_kind: str,
        duplicate_strategy: str = "skip",
        target_book_id: int | None = None,
        author: str = "",
        source_type: str = "wizard",
        stage_files: Callable[..., tuple[Path, list[dict]]] | None = None,
    ) -> dict:
        if content_kind == "unknown":
            raise ValueError("Choose raw or translated content mode before importing")
        if content_kind not in {"raw", "translated", "both"}:
            raise ValueError("Unsupported import content mode")
        if duplicate_strategy not in {"error", "skip", "overwrite"}:
            raise ValueError("Unsupported duplicate strategy")
        if not chapters:
            raise ValueError("No chapters to import")

        target_title = title.strip()
        if target_book_id is None and not target_title:
            raise ValueError("Book title is required")
        prepared = self._prepare_reviewed_import_items(chapters=chapters, content_kind=content_kind)

        staging_dir: Path | None = None
        finalized_paths: list[Path] = []
        imported = 0
        skipped = 0
        overwritten = 0
        chapter_ids: list[int] = []
        warnings: list[dict] = []

        with get_connection(self.db_path) as conn:
            initial_book = find_import_book_with_connection(
                conn,
                title=target_title,
                target_book_id=target_book_id,
            )
            if target_book_id is not None and not initial_book:
                raise ValueError(f"Book {target_book_id} not found")
            target_title = target_title or str((initial_book or {}).get("title") or "")
            for item in prepared:
                item["source_hash"] = detect_import_metadata(
                    title=target_title,
                    chapter_number=int(item["chapter_number"]),
                    chapter_title=str(item["chapter_title"]),
                    text=str(item["raw_text"] or item["translated_text"]),
                )["source_hash"]

            initial_book_id = int(initial_book["id"]) if initial_book else None
            existing = (
                list_active_import_chapters_with_connection(conn, initial_book_id)
                if initial_book_id is not None
                else []
            )
            initial_plan = self._classify_reviewed_import_items(
                prepared=prepared,
                existing_chapters=existing,
                duplicate_strategy=duplicate_strategy,
                book_id=initial_book_id,
            )
            staging_dir, staged_plan = (stage_files or self._stage_reviewed_import_files)(
                plan=initial_plan,
                book_title=target_title,
            )

            try:
                conn.execute("BEGIN IMMEDIATE")
                book = resolve_import_book_with_connection(
                    conn,
                    title=target_title,
                    author=author,
                    source=source_type,
                    target_book_id=target_book_id,
                )
                book_id = int(book["id"])
                current_plan = self._classify_reviewed_import_items(
                    prepared=prepared,
                    existing_chapters=list_active_import_chapters_with_connection(conn, book_id),
                    duplicate_strategy=duplicate_strategy,
                    book_id=book_id,
                )
                initial_signature = [
                    (item["action"], item["existing_id"], item["existing_fingerprint"])
                    for item in initial_plan
                ]
                current_signature = [
                    (item["action"], item["existing_id"], item["existing_fingerprint"])
                    for item in current_plan
                ]
                if current_signature != initial_signature:
                    raise ValueError("The target book changed after review; preview and confirm the import again")

                finalized_paths = self._finalize_reviewed_import_files(staged_plan)
                inserted_ids_by_number: dict[int, int] = {}
                batch_paths_by_number: dict[int, dict[str, Path | None]] = {}
                for item in staged_plan:
                    chapter_number = int(item["chapter_number"])
                    raw_path = item.get("raw_final_path")
                    translated_path = item.get("translated_final_path")
                    status = "translated" if translated_path else "imported"
                    if item["action"] == "REPLACE":
                        chapter_id = int(item["existing_id"]) or inserted_ids_by_number[chapter_number]
                        update_import_chapter_with_connection(
                            conn,
                            chapter_id=chapter_id,
                            title=str(item["chapter_title"]),
                            raw_text_path=raw_path,
                            translated_text_path=translated_path,
                            status=status,
                        )
                        previous_paths = batch_paths_by_number.get(chapter_number, {})
                        for content_kind, replacement_path in (
                            ("raw", raw_path),
                            ("translated", translated_path),
                        ):
                            previous_path = previous_paths.get(content_kind)
                            if replacement_path and previous_path and previous_path != replacement_path:
                                previous_path.unlink(missing_ok=True)
                        batch_paths_by_number[chapter_number] = {
                            "raw": raw_path or previous_paths.get("raw"),
                            "translated": translated_path or previous_paths.get("translated"),
                        }
                        overwritten += 1
                    else:
                        chapter_id = insert_import_chapter_with_connection(
                            conn,
                            book_id=book_id,
                            chapter_number=int(item["chapter_number"]),
                            title=str(item["chapter_title"]),
                            raw_text_path=raw_path,
                            translated_text_path=translated_path,
                            source_hash=str(item["source_hash"]) if raw_path else "",
                            status=status,
                        )
                        inserted_ids_by_number[chapter_number] = chapter_id
                        batch_paths_by_number[chapter_number] = {
                            "raw": raw_path,
                            "translated": translated_path,
                        }
                        imported += 1
                    item["chapter_id"] = chapter_id
                    chapter_ids.append(chapter_id)

                skipped_items = [item for item in initial_plan if item["action"] == "SKIP"]
                skipped = len(skipped_items)
                conn.commit()
            except Exception:
                conn.rollback()
                for path in finalized_paths:
                    path.unlink(missing_ok=True)
                raise
            finally:
                if staging_dir is not None:
                    shutil.rmtree(staging_dir, ignore_errors=True)

            for item in initial_plan:
                if item["action"] == "SKIP":
                    warnings.append({
                        "type": "duplicate_chapter",
                        "message": f"Skipped existing chapter {item['chapter_number']}",
                        "chapter_number": int(item["chapter_number"]), "title": str(item["chapter_title"]),
                    })
            if staged_plan:
                from app.mobile_api.services.glossary_service import GlossaryService
                from app.mobile_api.services.qa_service import QAService

                glossary_service = GlossaryService.from_db_path(self.db_path)
                qa_service = QAService(self.content_files)
                content_files = self.content_files
                conn.execute("BEGIN IMMEDIATE")
                snapshots = {row["id"]: dict(row) for row in conn.execute(
                    "SELECT * FROM chapters WHERE book_id = ? AND deleted_at IS NULL", (book_id,))}
                glossary_terms = [dict(row) for row in conn.execute(
                    "SELECT * FROM glossary_terms WHERE book_id IN (0, ?)", (book_id,))]
                for item in staged_plan:
                    chapter_id_for_followup = int(item["chapter_id"])
                    conn.execute("SAVEPOINT import_followup")
                    try:
                        snapshot = snapshots[chapter_id_for_followup]
                        glossary_service.extract_chapter_terms(book_id, chapter_id_for_followup,
                            connection=conn, chapter=snapshot)
                        if snapshot.get("translated_text_path"):
                            qa_service.run_deterministic_qa(book_id, chapter_id_for_followup,
                                connection=conn, chapter=snapshot, glossary_terms=glossary_terms,
                                source_text=content_files.get_chapter_source(chapter_id_for_followup, chapter=snapshot) or "",
                                translated_text=content_files.get_chapter_translation(chapter_id_for_followup, chapter=snapshot) or "")
                    except Exception:
                        conn.execute("ROLLBACK TO import_followup")
                        logger.warning("Post-import follow-up failed for book %s chapter %s", book_id, chapter_id_for_followup)
                        warnings.append({
                            "type": "post_import_qa_warning",
                            "message": "Imported content was saved, but glossary/QA follow-up did not complete.",
                            "chapter_number": int(item["chapter_number"]), "reason": "Follow-up failed; check server logs.",
                        })
                    finally:
                        conn.execute("RELEASE import_followup")
                try:
                    conn.commit()
                except Exception:
                    conn.rollback()
                    warnings.append({"type": "post_import_qa_warning",
                        "message": "Imported content was saved, but glossary/QA follow-up did not complete.",
                        "reason": "Follow-up failed; check server logs."})

        return {
            "book_id": book_id,
            "title": target_title,
            "content_kind": content_kind,
            "chapter_count": len(chapters),
            "imported_chapters": imported,
            "skipped_chapters": skipped,
            "overwritten_chapters": overwritten,
            "chapter_ids": chapter_ids,
            "warnings": warnings,
        }

    def import_from_file(
        self,
        title: str,
        chapter_number: int,
        chapter_title: str,
        file_path: Path,
        filename: str = "",
    ) -> dict:
        text = file_path.read_text(encoding="utf-8")
        metadata = detect_import_metadata(
            title=title,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            text=text,
            filename=filename or file_path.name,
        )
        detected_title = metadata["title"]
        detected_chapter_number = metadata["chapter_number"]
        detected_chapter_title = metadata["chapter_title"]
        book_id = self.books._book_id_for_title(detected_title)

        safe_title = self._safe_filename_part(detected_title) or "book"
        safe_chapter_title = self._safe_filename_part(detected_chapter_title) or "chapter"
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{safe_title}_ch{detected_chapter_number}_{safe_chapter_title}_{time.time_ns()}.txt"
        raw_path.write_text(text, encoding="utf-8")
        try:
            chapter_id = add_chapter(
                self.db_path,
                book_id,
                detected_chapter_number,
                detected_chapter_title,
                "",
                raw_text_path=raw_path,
                source_hash=metadata["source_hash"],
            )
        except Exception:
            raw_path.unlink(missing_ok=True)
            raise
        return {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "path": str(raw_path),
            "title": detected_title,
            "chapter_number": detected_chapter_number,
            "chapter_title": detected_chapter_title,
        }

    def add_url_note(
        self,
        title: str,
        url: str,
        notes: str = "",
        chapter_number: int = 1,
        chapter_title: str = "",
    ) -> int:
        # Save URL note as a text file in raw directory
        safe_title = "".join(c if c.isalnum() or c in "._-" else "_" for c in title or url)
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        content = f"URL: {url}\n\nNotes: {notes}\n\n{notes}"
        raw_path = write_versioned_text(raw_dir, f"{safe_title}_url", content)
        book_id = self.books.create_book(title) if not get_book_by_title(self.db_path, title) else get_book_by_title(self.db_path, title)["id"]
        try:
            add_chapter(self.db_path, book_id, chapter_number, chapter_title or "URL Note", "", raw_text_path=raw_path)
        except Exception:
            raw_path.unlink(missing_ok=True)
            raise
        return get_book_by_title(self.db_path, title)["id"]
