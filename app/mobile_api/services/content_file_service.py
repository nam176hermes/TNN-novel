from __future__ import annotations

from pathlib import Path

from app.database.db import get_chapter_by_id
from app.storage.artifact_paths import ArtifactClass, require_artifact_file
from app.translation.idiom_correction import clean_translation_layout


class ContentFileService:
    """Read active chapter artifacts through the canonical contained-path resolver."""

    def __init__(
        self,
        *,
        data_dir: Path,
        db_path: Path,
        legacy_artifact_root: Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.legacy_artifact_root = Path(legacy_artifact_root) if legacy_artifact_root is not None else None

    def resolve_artifact_file(self, value: str | Path | None, artifact_class: ArtifactClass) -> Path:
        return require_artifact_file(
            value,
            artifact_class=artifact_class,
            data_root=self.data_dir,
            old_root=self.legacy_artifact_root,
        )

    def get_chapter_source(self, chapter_id: int, *, chapter=None) -> str | None:
        chapter = chapter if chapter is not None else get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or not chapter.get("raw_text_path"):
            return None
        path = self.resolve_artifact_file(chapter["raw_text_path"], ArtifactClass.RAW)
        return clean_translation_layout(path.read_text(encoding="utf-8"))

    def get_chapter_translation(self, chapter_id: int, *, chapter=None) -> str | None:
        chapter = chapter if chapter is not None else get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or not chapter.get("translated_text_path"):
            return None
        path = self.resolve_artifact_file(chapter["translated_text_path"], ArtifactClass.TRANSLATED)
        return path.read_text(encoding="utf-8")

    def get_chapter_content(self, chapter_id: int, *, chapter=None) -> dict | None:
        chapter = chapter if chapter is not None else get_chapter_by_id(self.db_path, chapter_id)
        text = self.get_chapter_translation(chapter_id, chapter=chapter)
        if text is None:
            return None
        html = ""
        if chapter and chapter.get("content_html_path"):
            path = self.resolve_artifact_file(chapter["content_html_path"], ArtifactClass.HTML)
            html = path.read_text(encoding="utf-8")
        return {"text": text, "html": html}
