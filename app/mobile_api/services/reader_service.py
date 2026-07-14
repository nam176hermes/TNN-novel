from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.database import reader_repository as reader_repo
from app.database.db import get_book_by_id, get_chapter_by_id, list_chapters
from app.mobile_api.services.content_file_service import ContentFileService


class ReaderService:
    """Orchestrate Reader content, progress, annotations, and sync state."""

    def __init__(self, *, db_path: Path, content_file_service: ContentFileService) -> None:
        self.db_path = Path(db_path)
        self.content_file_service = content_file_service

    def get_chapter_source(self, chapter_id: int) -> str | None:
        return self.content_file_service.get_chapter_source(chapter_id)

    def get_chapter_translation(self, chapter_id: int) -> str | None:
        return self.content_file_service.get_chapter_translation(chapter_id)

    def get_chapter_content(self, chapter_id: int) -> dict | None:
        return self.content_file_service.get_chapter_content(chapter_id)

    def _get_chapter_for_book(self, book_id: int, chapter_id: int) -> dict | None:
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or chapter.get("book_id") != book_id:
            return None
        return chapter

    def get_reader_state(self, book_id: int) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None
        return {
            "progress": reader_repo.get_reader_progress(self.db_path, book_id),
            "annotations": reader_repo.list_reader_annotations(self.db_path, book_id),
        }

    def save_reader_progress(
        self,
        book_id: int,
        *,
        chapter_id: int,
        mode: str = "scroll",
        percent: int = 0,
        paragraph_index: int = 0,
        char_offset: int = 0,
        absolute_char_offset: int = 0,
        page_index: int = 0,
        anchor: dict | None = None,
        updated_at: str | None = None,
    ) -> dict | None:
        if not self._get_chapter_for_book(book_id, chapter_id):
            return None
        return reader_repo.upsert_reader_progress(
            self.db_path,
            book_id=book_id,
            chapter_id=chapter_id,
            mode=mode,
            percent=percent,
            paragraph_index=paragraph_index,
            char_offset=char_offset,
            absolute_char_offset=absolute_char_offset,
            page_index=page_index,
            anchor=anchor,
            updated_at=updated_at,
        )

    def list_reader_annotations(self, book_id: int) -> list[dict] | None:
        if not get_book_by_id(self.db_path, book_id):
            return None
        return reader_repo.list_reader_annotations(self.db_path, book_id)

    def create_reader_annotation(
        self,
        book_id: int,
        chapter_id: int,
        *,
        kind: str,
        paragraph_index: int = 0,
        char_start: int = 0,
        char_end: int = 0,
        selected_text: str = "",
        note: str = "",
        color: str = "yellow",
        client_id: str = "",
    ) -> dict | None:
        if not self._get_chapter_for_book(book_id, chapter_id):
            return None
        return reader_repo.add_reader_annotation(
            self.db_path,
            book_id=book_id,
            chapter_id=chapter_id,
            kind=kind,
            paragraph_index=paragraph_index,
            char_start=char_start,
            char_end=char_end,
            selected_text=selected_text,
            note=note,
            color=color,
            client_id=client_id,
        )

    def import_reader_annotations(self, book_id: int, *, annotations: list[dict]) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None

        chapters = list_chapters(self.db_path, book_id)
        chapters_by_number = {
            int(chapter.get("chapter_number") or 0): chapter
            for chapter in chapters
            if int(chapter.get("chapter_number") or 0) > 0
        }
        existing_annotations = reader_repo.list_reader_annotations(self.db_path, book_id, include_deleted=True)
        existing_signatures = {
            (
                int(annotation.get("chapter_id") or 0),
                str(annotation.get("kind") or ""),
                int(annotation.get("paragraph_index") or 0),
                int(annotation.get("char_start") or 0),
                int(annotation.get("char_end") or 0),
                str(annotation.get("selected_text") or ""),
                str(annotation.get("note") or ""),
                str(annotation.get("color") or ""),
            )
            for annotation in existing_annotations
        }
        imported_annotations: list[dict] = []
        imported = 0
        duplicates = 0
        invalid = 0

        def resolved_chapter_id(annotation: dict) -> int | None:
            raw_chapter_id = int(annotation.get("chapter_id") or 0)
            if raw_chapter_id and self._get_chapter_for_book(book_id, raw_chapter_id):
                return raw_chapter_id
            raw_chapter_number = int(annotation.get("chapter_number") or 0)
            chapter = chapters_by_number.get(raw_chapter_number)
            return int(chapter["id"]) if chapter else None

        for annotation in annotations:
            chapter_id = resolved_chapter_id(annotation)
            if not chapter_id:
                invalid += 1
                continue

            client_id = str(annotation.get("client_id") or "").strip()
            if client_id and reader_repo.get_reader_annotation_by_client_id(
                self.db_path,
                book_id,
                client_id,
                include_deleted=True,
            ):
                duplicates += 1
                continue

            signature = (
                chapter_id,
                str(annotation.get("kind") or "highlight"),
                int(annotation.get("paragraph_index") or 0),
                int(annotation.get("char_start") or 0),
                int(annotation.get("char_end") or 0),
                str(annotation.get("selected_text") or ""),
                str(annotation.get("note") or ""),
                str(annotation.get("color") or "yellow"),
            )
            if signature in existing_signatures:
                duplicates += 1
                continue

            created = reader_repo.add_reader_annotation(
                self.db_path,
                book_id=book_id,
                chapter_id=chapter_id,
                kind=str(annotation.get("kind") or "highlight"),
                paragraph_index=int(annotation.get("paragraph_index") or 0),
                char_start=int(annotation.get("char_start") or 0),
                char_end=int(annotation.get("char_end") or 0),
                selected_text=str(annotation.get("selected_text") or ""),
                note=str(annotation.get("note") or ""),
                color=str(annotation.get("color") or "yellow"),
                client_id=client_id,
            )
            if not created:
                invalid += 1
                continue
            imported += 1
            imported_annotations.append(created)
            existing_signatures.add(signature)

        return {
            "summary": {
                "imported": imported,
                "skipped": duplicates + invalid,
                "duplicates": duplicates,
                "invalid": invalid,
            },
            "annotations": imported_annotations,
        }

    def update_reader_annotation(self, book_id: int, annotation_id: int, **updates) -> dict | None:
        if not reader_repo.get_reader_annotation(self.db_path, book_id, annotation_id):
            return None
        return reader_repo.update_reader_annotation(
            self.db_path,
            book_id=book_id,
            annotation_id=annotation_id,
            kind=updates.get("kind"),
            paragraph_index=updates.get("paragraph_index"),
            char_start=updates.get("char_start"),
            char_end=updates.get("char_end"),
            selected_text=updates.get("selected_text"),
            note=updates.get("note"),
            color=updates.get("color"),
            client_id=updates.get("client_id"),
        )

    def delete_reader_annotation(self, book_id: int, annotation_id: int) -> bool:
        return reader_repo.soft_delete_reader_annotation(self.db_path, book_id, annotation_id)

    @staticmethod
    def _sync_timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _sync_conflict(
        *,
        entity: str,
        resolution: str,
        reason: str,
        id: int | None = None,
        client_id: str | None = None,
        server_annotation: dict | None = None,
        client_annotation: dict | None = None,
    ) -> dict:
        conflict = {
            "entity": entity,
            "id": id,
            "client_id": client_id,
            "resolution": resolution,
            "reason": reason,
        }
        if server_annotation is not None:
            conflict["server_annotation"] = dict(server_annotation)
        if client_annotation is not None:
            conflict["client_annotation"] = dict(client_annotation)
        return conflict

    @staticmethod
    def _sync_annotation_differs(existing: dict, incoming: dict) -> bool:
        comparable_fields = (
            "chapter_id",
            "kind",
            "paragraph_index",
            "char_start",
            "char_end",
            "selected_text",
            "note",
            "color",
        )
        for field in comparable_fields:
            existing_value = existing.get(field)
            incoming_value = incoming.get(field)
            if field in {"chapter_id", "paragraph_index", "char_start", "char_end"}:
                existing_value = int(existing_value or 0)
                incoming_value = int(incoming_value or 0)
            else:
                existing_value = str(existing_value or "")
                incoming_value = str(incoming_value or "")
            if existing_value != incoming_value:
                return True
        return bool(existing.get("deleted_at")) != bool(incoming.get("deleted_at"))

    @staticmethod
    def _sync_progress_differs(existing: dict, incoming: dict) -> bool:
        comparable_fields = (
            "chapter_id",
            "mode",
            "percent",
            "paragraph_index",
            "char_offset",
            "absolute_char_offset",
            "page_index",
        )
        for field in comparable_fields:
            existing_value = existing.get(field)
            incoming_value = incoming.get(field)
            if field == "mode":
                existing_value = str(existing_value or "scroll")
                incoming_value = str(incoming_value or "scroll")
            else:
                existing_value = int(existing_value or 0)
                incoming_value = int(incoming_value or 0)
            if existing_value != incoming_value:
                return True
        return False

    def sync_reader_state(
        self,
        book_id: int,
        *,
        device_id: str = "",
        last_sync_at: str | None = None,
        progress: dict | None = None,
        annotations: list[dict] | None = None,
    ) -> dict | None:
        if not get_book_by_id(self.db_path, book_id):
            return None

        conflicts: list[dict] = []
        has_sync_base = bool(last_sync_at and last_sync_at.strip())
        last_sync_timestamp = self._sync_timestamp(last_sync_at)

        if progress:
            chapter_id = int(progress.get("chapter_id") or 0)
            if self._get_chapter_for_book(book_id, chapter_id):
                server_progress = reader_repo.get_reader_progress(self.db_path, book_id)
                client_updated_at = str(progress.get("updated_at") or "").strip()
                client_timestamp = self._sync_timestamp(client_updated_at)
                server_timestamp = self._sync_timestamp(server_progress.get("updated_at") if server_progress else None)
                if server_progress is None or client_timestamp > server_timestamp:
                    if server_progress is not None and has_sync_base and server_timestamp > last_sync_timestamp:
                        conflicts.append(
                            self._sync_conflict(
                                entity="progress",
                                id=None,
                                client_id=device_id or None,
                                resolution="client_won",
                                reason="diverged_since_last_sync",
                            )
                        )
                    self.save_reader_progress(
                        book_id,
                        chapter_id=chapter_id,
                        mode=progress.get("mode") or "scroll",
                        percent=int(progress.get("percent") or 0),
                        paragraph_index=int(progress.get("paragraph_index") or 0),
                        char_offset=int(progress.get("char_offset") or 0),
                        absolute_char_offset=int(progress.get("absolute_char_offset") or 0),
                        page_index=int(progress.get("page_index") or 0),
                        anchor=progress.get("anchor") if isinstance(progress.get("anchor"), dict) else None,
                        updated_at=(
                            client_updated_at
                            if client_timestamp > datetime.min.replace(tzinfo=timezone.utc)
                            else None
                        ),
                    )
                elif client_timestamp < server_timestamp:
                    conflicts.append(
                        self._sync_conflict(
                            entity="progress",
                            id=None,
                            client_id=device_id or None,
                            resolution="server_won",
                            reason="server_newer",
                        )
                    )
                elif server_progress is not None and self._sync_progress_differs(server_progress, progress):
                    conflicts.append(
                        self._sync_conflict(
                            entity="progress",
                            id=None,
                            client_id=device_id or None,
                            resolution="server_won",
                            reason="same_timestamp_different",
                        )
                    )

        for annotation in annotations or []:
            annotation_id = annotation.get("id")
            client_id = annotation.get("client_id")
            existing = (
                reader_repo.get_reader_annotation(
                    self.db_path,
                    book_id,
                    int(annotation_id),
                    include_deleted=True,
                )
                if annotation_id is not None
                else None
            )
            if existing is None and client_id:
                existing = reader_repo.get_reader_annotation_by_client_id(
                    self.db_path,
                    book_id,
                    str(client_id),
                    include_deleted=True,
                )
            client_timestamp = self._sync_timestamp(annotation.get("updated_at") or annotation.get("deleted_at"))
            server_timestamp = self._sync_timestamp(existing.get("updated_at") if existing else None)
            client_updated_at = str(annotation.get("updated_at") or "").strip()
            client_created_at = str(annotation.get("created_at") or "").strip()
            client_deleted_at = str(annotation.get("deleted_at") or "").strip()
            valid_client_updated_at = (
                client_updated_at
                if self._sync_timestamp(client_updated_at) > datetime.min.replace(tzinfo=timezone.utc)
                else None
            )
            valid_client_created_at = (
                client_created_at
                if self._sync_timestamp(client_created_at) > datetime.min.replace(tzinfo=timezone.utc)
                else None
            )
            valid_client_deleted_at = (
                client_deleted_at
                if self._sync_timestamp(client_deleted_at) > datetime.min.replace(tzinfo=timezone.utc)
                else None
            )

            if existing:
                if client_timestamp > server_timestamp:
                    if has_sync_base and server_timestamp > last_sync_timestamp:
                        conflicts.append(
                            self._sync_conflict(
                                entity="annotation",
                                id=existing["id"],
                                client_id=client_id,
                                resolution="client_won",
                                reason="diverged_since_last_sync",
                                server_annotation=existing,
                                client_annotation=annotation,
                            )
                        )
                    if annotation.get("deleted_at"):
                        reader_repo.soft_delete_reader_annotation(
                            self.db_path,
                            book_id,
                            existing["id"],
                            deleted_at=valid_client_deleted_at,
                            updated_at=valid_client_updated_at or valid_client_deleted_at,
                        )
                    elif not existing.get("deleted_at") and self._get_chapter_for_book(
                        book_id,
                        annotation["chapter_id"],
                    ):
                        reader_repo.update_reader_annotation(
                            self.db_path,
                            book_id=book_id,
                            annotation_id=existing["id"],
                            kind=annotation.get("kind"),
                            paragraph_index=annotation.get("paragraph_index"),
                            char_start=annotation.get("char_start"),
                            char_end=annotation.get("char_end"),
                            selected_text=annotation.get("selected_text"),
                            note=annotation.get("note"),
                            color=annotation.get("color"),
                            client_id=client_id,
                            updated_at=valid_client_updated_at,
                        )
                    else:
                        conflicts.append(
                            self._sync_conflict(
                                entity="annotation",
                                id=existing["id"],
                                client_id=client_id,
                                resolution="server_won",
                                reason="server_deleted",
                                server_annotation=existing,
                                client_annotation=annotation,
                            )
                        )
                elif client_timestamp < server_timestamp:
                    conflicts.append(
                        self._sync_conflict(
                            entity="annotation",
                            id=existing["id"],
                            client_id=client_id,
                            resolution="server_won",
                            reason="server_newer",
                            server_annotation=existing,
                            client_annotation=annotation,
                        )
                    )
                elif self._sync_annotation_differs(existing, annotation):
                    conflicts.append(
                        self._sync_conflict(
                            entity="annotation",
                            id=existing["id"],
                            client_id=client_id,
                            resolution="server_won",
                            reason="same_timestamp_different",
                            server_annotation=existing,
                            client_annotation=annotation,
                        )
                    )
                continue

            if annotation.get("deleted_at"):
                continue
            if not self._get_chapter_for_book(book_id, int(annotation.get("chapter_id") or 0)):
                continue
            reader_repo.add_reader_annotation(
                self.db_path,
                book_id=book_id,
                chapter_id=int(annotation["chapter_id"]),
                kind=annotation.get("kind") or "highlight",
                paragraph_index=int(annotation.get("paragraph_index") or 0),
                char_start=int(annotation.get("char_start") or 0),
                char_end=int(annotation.get("char_end") or 0),
                selected_text=annotation.get("selected_text") or "",
                note=annotation.get("note") or "",
                color=annotation.get("color") or "yellow",
                client_id=str(client_id or "").strip(),
                created_at=valid_client_created_at,
                updated_at=valid_client_updated_at,
            )

        return {
            "progress": reader_repo.get_reader_progress(self.db_path, book_id),
            "annotations": reader_repo.list_reader_annotations(self.db_path, book_id, include_deleted=True),
            "conflicts": conflicts,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
