from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    import edge_tts
except ModuleNotFoundError:  # pragma: no cover - exercised through runtime branch
    edge_tts = SimpleNamespace(Communicate=None)

from app.config import settings
from app.database.chapter_repository import file_digest
from app.storage.chapter_content import retire_artifact
from app.database.db import (
    get_book_by_id,
    get_chapter_by_id,
    get_connection,
    get_operator_user_id,
    record_operational_event,
    update_chapter_paths,
)
from app.services.tts.audio_merger import AudioMetadata, merge_book_m4b, merge_chapter_audio
from app.services.tts.audio_qa import AudioQAResult, analyze_audio
from app.services.tts.chunker import TTSChunk, chunk_text
from app.services.tts.f5_vietnamese_engine import (
    F5VietnameseConfig,
    F5VietnameseEngine,
    TTSConfigurationError,
    TTSDependencyError,
    TTSEngineError,
    VoiceConfig,
    stable_audio_cache_key,
)
from app.services.tts.availability import is_f5_provider, require_tts_runtime_available
from app.services.tts.text_normalizer import normalize_text
from app.translation.idiom_correction import clean_translation_layout
from app.utils.asyncio_bridge import run_coro_sync
from app.storage.artifact_paths import ArtifactClass, ArtifactPathError, require_artifact_file

logger = logging.getLogger(__name__)

LegacyTTSCallable = Callable[..., None]


@dataclass(frozen=True)
class TTSJobReport:
    job_id: str
    status: str
    book_id: int
    chapter_id: int
    output_mp3_path: str = ""
    output_m4b_path: str = ""
    report_json_path: str = ""
    progress: int = 0
    error_message: str = ""


def text_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def voice_config_hash(voice_config: VoiceConfig, model_config: F5VietnameseConfig) -> str:
    return stable_audio_cache_key("", voice_config=voice_config, model_config=model_config)


def _safe_error(exc: BaseException | str) -> str:
    message = str(exc)
    message = re.sub(r"(?i)(api[_-]?key|token|secret|password)=?[^\s,;]+", r"\1=[redacted]", message)
    message = re.sub(r"(/[A-Za-z0-9._~+\-]+){2,}", "[path]", message)
    message = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", message)
    message = message.replace("\n", " ").strip()
    return message[:500] or "TTS failed. Check server logs."


def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class EdgeTtsChunkEngine:
    def __init__(self, voice_config: VoiceConfig):
        self.voice_config = voice_config

    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config: VoiceConfig) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def run() -> None:
            communicate_cls = getattr(edge_tts, "Communicate", None)
            if communicate_cls is None:
                raise TTSDependencyError("edge-tts is not installed. Install edge-tts or use F5 Vietnamese TTS.")
            voice = voice_config.voice_id if voice_config.voice_id != "default" else settings.edge_tts_voice
            communicate = communicate_cls(
                normalized_text,
                voice,
                rate="+0%",
                volume="+0%",
            )
            await communicate.save(str(output_path))

        run_coro_sync(run())
        return output_path


class TTSPipeline:
    def __init__(
        self,
        db_path: Path | None = None,
        data_dir: Path | None = None,
        *,
        engine_factory: Callable[[], Any] | None = None,
        legacy_fallback: LegacyTTSCallable | None = None,
    ):
        self.db_path = db_path or settings.db_path
        self.data_dir = data_dir or settings.resolved_data_dir
        self.engine_factory = engine_factory
        self.legacy_fallback = legacy_fallback
        self.legacy_artifact_root = settings.artifact_legacy_root
        self._engine = None
        self._engine_identity = None
        self._batch_snapshot = None

    def generate_chapter(
        self,
        *,
        book_id: int,
        chapter_id: int,
        job_id: str = "",
        voice_config: dict[str, Any] | None = None,
        provider: str | None = None,
        resume: bool = True,
        parent_job_id: str = "",
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> TTSJobReport:
        job_id = job_id or f"tts_{uuid.uuid4().hex}"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", job_id):
            raise ValueError("Invalid TTS job id")
        book = get_book_by_id(self.db_path, book_id)
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not book or not chapter or chapter.get("book_id") != book_id:
            raise ValueError("Book or chapter not found for TTS")
        if not chapter.get("translated_text_path"):
            raise ValueError("Chapter has no translated text for TTS")
        existing_job = self.get_job_status(job_id)
        if existing_job and (existing_job["book_id"] != book_id or existing_job["chapter_id"] != chapter_id):
            raise ValueError("TTS job belongs to a different chapter")
        source_path = require_artifact_file(chapter["translated_text_path"], artifact_class=ArtifactClass.TRANSLATED,
            data_root=self.data_dir, old_root=self.legacy_artifact_root)
        source_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        text = clean_translation_layout(source_bytes.decode("utf-8"))
        if not text.strip():
            raise ValueError("Chapter has no translated text for TTS")
        snapshot = self._decode_json(existing_job.get("input_snapshot_json", ""), {}) if existing_job else {}
        if existing_job and not snapshot:
            raise ValueError("Legacy TTS input is unverified; start a new job")
        if not snapshot and parent_job_id and self._batch_snapshot is not None:
            snapshot = json.loads(json.dumps(self._batch_snapshot))
            snapshot["content_revision"] = chapter["content_revision"]
        if snapshot:
            if provider is not None and provider != snapshot["model"]["provider"]:
                raise ValueError("TTS input provider has changed; start a new job")
            if existing_job and (snapshot["content_revision"] != chapter["content_revision"] or source_hash != existing_job["source_translation_hash"]):
                raise ValueError("TTS input has changed; start a new job")
            voice = VoiceConfig(**snapshot["voice"])
            config = dict(snapshot["model"])
            config["cache_dir"] = Path(config["cache_dir"])
            model_config = F5VietnameseConfig(**config)
            if existing_job and voice_config is not None and voice_config_hash(VoiceConfig.from_mapping(voice_config), model_config) != existing_job["voice_config_hash"]:
                raise ValueError("TTS input voice has changed; start a new job")
            if existing_job and voice_config_hash(voice, model_config) != existing_job["voice_config_hash"]:
                raise ValueError("TTS input reference or model has changed; start a new job")
        else:
            voice = VoiceConfig.from_mapping(voice_config)
            model_config = F5VietnameseConfig.from_settings(cache_dir=self.data_dir / "audio" / "cache")
            if provider is not None:
                model_config = replace(model_config, provider=provider)
            snapshot = {"version": 1, "content_revision": chapter["content_revision"], "voice": asdict(voice),
                "model": {**asdict(model_config), "cache_dir": str(model_config.cache_dir)},
                "normalizer": settings.tts_normalizer, "max_chars": settings.tts_chunk_max_chars,
                "max_sentences": settings.tts_chunk_max_sentences, "qa_enabled": settings.tts_enable_qa,
                "retry_budget": max(1, settings.tts_qa_retries + 1, settings.tts_chunk_retries + 1)}
        if parent_job_id and self._batch_snapshot is None:
            self._batch_snapshot = snapshot
        fingerprint = voice_config_hash(voice, model_config)
        if snapshot.get("voice_fingerprint", fingerprint) != fingerprint:
            raise ValueError("TTS batch reference or model has changed; start a new job")
        snapshot["voice_fingerprint"] = fingerprint
        if is_f5_provider(model_config.provider):
            require_tts_runtime_available(provider=model_config.provider)
        normalized = normalize_text(text, backend=snapshot["normalizer"])
        chunks = chunk_text(normalized.text, chapter_id=chapter_id,
            max_chars=snapshot["max_chars"], max_sentences=snapshot["max_sentences"])
        if not chunks:
            raise ValueError("No text chunks available for TTS")
        if existing_job and existing_job["text_hash"] != text_hash(normalized.text):
            raise ValueError("TTS input normalization has changed; start a new job")
        owner_user_id = str(book.get("owner_user_id") or "") or get_operator_user_id(self.db_path)
        output_dir = self.data_dir / "audio" / "tts_jobs" / job_id
        chunk_dir = output_dir / "chunks"
        report_path = output_dir / "report.json"
        output_path = self.data_dir / "audio" / f"book{book_id}_ch{chapter_id}_{uuid.uuid4().hex}.mp3"
        output_dir.mkdir(parents=True, exist_ok=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)

        with get_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT content_revision FROM chapters WHERE id = ? AND deleted_at IS NULL", (chapter_id,)).fetchone()
            if not current or current["content_revision"] != snapshot["content_revision"] or file_digest(source_path) != source_hash:
                raise ValueError("TTS input has changed; start a new job")
            conn.execute("UPDATE chapters SET translation_hash = ? WHERE id = ? AND translation_hash IS NULL", (source_hash, chapter_id))
            self._upsert_job(
                conn,
                job_id=job_id,
                book_id=book_id,
                chapter_id=chapter_id,
                provider=model_config.provider,
                model=model_config.model,
                owner_user_id=owner_user_id,
                voice_hash=fingerprint,
                chapter_text_hash=text_hash(normalized.text),
                report_path=report_path, source_hash=source_hash, snapshot=snapshot, parent_job_id=parent_job_id,
            )
            self._prepare_chunks(conn, job_id, chunks)
            conn.commit()

        record_operational_event(
            self.db_path,
            event_type="tts_start",
            severity="info",
            source="tts",
            message="TTS chapter generation started",
            job_id=job_id,
            owner_user_id=owner_user_id,
            details={"book_id": book_id, "chapter_id": chapter_id, "provider": settings.tts_provider},
        )

        chunk_artifacts: list[tuple[TTSChunk, Path]] = []
        try:
            engine = self._build_engine(voice, model_config)
            for chunk in chunks:
                if self._is_cancelled(job_id) or (cancel_check and cancel_check()):
                    self.cancel_job(job_id)
                    return self._write_report(job_id)
                existing = self._get_chunk(job_id, chunk.chunk_index)
                existing_path = self._existing_completed_chunk_path(existing)
                if resume and existing_path is not None:
                    qa = analyze_audio(existing_path, text=chunk.normalized_text) if snapshot["qa_enabled"] else AudioQAResult(True)
                    if qa.passed:
                        chunk_artifacts.append((chunk, existing_path))
                        continue

                suffix = ".mp3" if model_config.provider.lower() == "edge_tts" else ".wav"
                chunk_path = chunk_dir / f"chunk_{chunk.chunk_index:04d}{suffix}"
                self._update_chunk(job_id, chunk.chunk_index, status="running", error_message="")
                produced_path = self._synthesize_and_qa(engine, chunk, chunk_path, voice,
                    qa_enabled=snapshot["qa_enabled"], retry_budget=snapshot["retry_budget"],
                    cancel_check=lambda: (cancel_check and cancel_check()) or self._is_cancelled(job_id))
                chunk_artifacts.append((chunk, produced_path))
                progress = int((len(chunk_artifacts) / len(chunks)) * 85)
                self._update_job(job_id, status="running", progress=progress, error_message="")
                if progress_callback:
                    progress_callback(progress, f"TTS chunk {chunk.chunk_index + 1}/{len(chunks)}")

            if self._is_cancelled(job_id) or (cancel_check and cancel_check()):
                self.cancel_job(job_id)
                return self._write_report(job_id)

            self._validate_chunk_outputs(job_id, chunk_artifacts, expected_count=len(chunks))
            chunk_paths = [path for _, path in chunk_artifacts]
            metadata = AudioMetadata(
                title=f"{book['title']} - Chương {chapter['chapter_number']}",
                author=str(book.get("author") or ""),
                chapter_number=int(chapter.get("chapter_number") or 0),
                source_book=str(book.get("title") or ""),
            )
            merge_chapter_audio(
                chunk_paths,
                output_path,
                metadata=metadata,
                sample_rate=model_config.sample_rate, rate=voice.rate, volume=voice.volume,
            )
            self._validate_final_output(output_path, text=normalized.text, label="chapter MP3", qa_enabled=snapshot["qa_enabled"])
            if self._is_cancelled(job_id) or (cancel_check and cancel_check()):
                self.cancel_job(job_id)
                output_path.unlink(missing_ok=True)
                return self._write_report(job_id)
            update_chapter_paths(self.db_path, chapter_id, audio_path=output_path, status="audio_done",
                expected_content_revision=snapshot["content_revision"], expected_translation_hash=source_hash,
                publication_job_id=job_id)
            retire_artifact(chapter.get("audio_path"), self.data_dir, self.db_path)
            self._update_job(job_id, status="completed", progress=100, output_mp3_path=str(output_path), error_message="")
            record_operational_event(
                self.db_path,
                event_type="tts_complete",
                severity="info",
                source="tts",
                message="TTS chapter generation completed",
                job_id=job_id,
                owner_user_id=owner_user_id,
                details={"book_id": book_id, "chapter_id": chapter_id, "chunk_count": len(chunks)},
            )
        except (TTSDependencyError, TTSConfigurationError) as exc:
            if self.legacy_fallback is not None and not is_f5_provider(model_config.provider):
                logger.warning("Using configured legacy TTS fallback for job %s", job_id)
                return self._run_legacy_fallback(
                    job_id=job_id,
                    book=book,
                    chapter=chapter,
                    text=text,
                    voice=voice,
                    output_path=output_path,
                    report_path=report_path,
                    reason=exc,
                    snapshot=snapshot, source_hash=source_hash, cancel_check=cancel_check,
                )
            self._fail_job(job_id, exc)
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            self._fail_job(job_id, exc)
        return self._write_report(job_id)

    def retry_failed_chunks(self, job_id: str) -> TTSJobReport:
        job = self.get_job_status(job_id)
        if not job:
            raise ValueError("TTS job not found")
        return self.generate_chapter(
            book_id=int(job["book_id"]),
            chapter_id=int(job["chapter_id"]),
            job_id=job_id,
            resume=True, parent_job_id=str(job.get("parent_job_id") or ""),
        )

    def cancel_job(self, job_id: str) -> bool:
        now = self._now()
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE tts_jobs SET status = 'cancelled', updated_at = ? WHERE (id = ? OR parent_job_id = ?) AND status != 'completed'",
                (now, job_id, job_id),
            )
            conn.execute(
                """
                UPDATE tts_chunks
                SET status = 'cancelled', updated_at = ?
                WHERE job_id IN (SELECT id FROM tts_jobs WHERE id = ? OR parent_job_id = ?) AND status IN ('pending', 'running')
                """,
                (now, job_id, job_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            job = _row_to_dict(conn.execute("SELECT * FROM tts_jobs WHERE id = ?", (job_id,)).fetchone())
            if not job:
                return None
            chunk_rows = conn.execute(
                """
                SELECT id, job_id, chunk_index, text_hash, status, wav_path, mp3_path,
                       duration_seconds, qa_status, qa_report_json, error_message, created_at, updated_at
                FROM tts_chunks
                WHERE job_id = ?
                ORDER BY chunk_index
                """,
                (job_id,),
            ).fetchall()
        chunks: list[dict[str, Any]] = []
        for row in chunk_rows:
            item = dict(row)
            item["qa_report"] = self._decode_json(item.pop("qa_report_json", "{}"), {})
            chunks.append(item)
        if str(job.get("status") or "") == "completed":
            job["error_message"] = ""
        job["chunks"] = chunks
        job["audio_summary"] = self._build_audio_summary(job, chunks)
        return job

    def get_download_path(self, job_id: str, output_format: str = "mp3") -> Path | None:
        job = self.get_job_status(job_id)
        if not job or job["status"] != "completed" or not self._job_content_is_current(job):
            return None
        key = "output_m4b_path" if output_format.lower() == "m4b" else "output_mp3_path"
        return self._resolved_output_path(job.get(key))

    def _job_content_is_current(self, job):
        chapter = get_chapter_by_id(self.db_path, job["chapter_id"])
        if not chapter:
            return False
        snapshot = self._decode_json(job.get("input_snapshot_json", ""), {})
        return (chapter.get("audio_status") != "stale" if not snapshot else (chapter["content_revision"] == snapshot["content_revision"]
                                and chapter["translation_hash"] == job.get("source_translation_hash"))
                )

    def validate_retry(self, job_id):
        job = self.get_job_status(job_id)
        if not job:
            raise ValueError("TTS job not found")
        snapshot = self._decode_json(job.get("input_snapshot_json", ""), {})
        if not snapshot or not self._job_content_is_current(job):
            raise ValueError("TTS input has changed or is unverified; start a new job")
        config = {**snapshot["model"], "cache_dir": Path(snapshot["model"]["cache_dir"])}
        if voice_config_hash(VoiceConfig(**snapshot["voice"]), F5VietnameseConfig(**config)) != job["voice_config_hash"]:
            raise ValueError("TTS input reference has changed; start a new job")

    def get_child_jobs(self, parent_job_id):
        with get_connection(self.db_path) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id, chapter_id, status, progress FROM tts_jobs WHERE parent_job_id = ? ORDER BY created_at, chapter_id",
                (parent_job_id,))]

    def generate_book_m4b(self, book_id: int, *, job_id: str = "", allow_partial: bool = False) -> Path:
        if job_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", job_id):
            raise ValueError("Invalid TTS job id")
        book = get_book_by_id(self.db_path, book_id)
        if not book:
            raise ValueError("Book not found")
        from app.database.db import list_chapters
        from app.export.m4b_exporter import select_audiobook_chapters, validate_audiobook_snapshot

        chapter_rows = sorted(
            list_chapters(self.db_path, book_id),
            key=lambda item: int(item.get("chapter_number") or 0),
        )
        resolved_chapters = []
        for chapter in chapter_rows:
            resolved = dict(chapter)
            if not chapter.get("audio_path"):
                resolved_chapters.append(resolved)
                continue
            try:
                resolved["audio_path"] = str(
                    require_artifact_file(
                        chapter["audio_path"],
                        artifact_class=ArtifactClass.AUDIO,
                        data_root=self.data_dir,
                        old_root=getattr(self, "legacy_artifact_root", settings.artifact_legacy_root),
                    )
                )
            except ArtifactPathError:
                resolved["audio_path"] = ""
            resolved_chapters.append(resolved)
        included, missing = select_audiobook_chapters(resolved_chapters, allow_partial=allow_partial)
        chapter_paths = [Path(chapter["audio_path"]) for chapter in included]
        output_path = self.data_dir / "audio" / f"book{book_id}_{job_id or 'export'}_{uuid.uuid4().hex}.m4b"
        result = merge_book_m4b(
            chapter_paths,
            output_path,
            metadata=AudioMetadata(title=str(book.get("title") or ""), author=str(book.get("author") or ""), source_book=str(book.get("title") or "")),
            chapter_titles=[chapter.get("translated_title") or chapter["title"] for chapter in included],
        )
        self._validate_output_file(result, "book M4B")
        try:
            validate_audiobook_snapshot(chapter_rows, list_chapters(self.db_path, book_id))
        except ValueError:
            result.unlink(missing_ok=True)
            raise
        result.with_suffix(".manifest.json").write_text(json.dumps({"partial": bool(missing), "missing_chapter_ids": missing, "chapter_ids": [chapter["id"] for chapter in included]}), encoding="utf-8")
        return result

    def _build_engine(self, voice: VoiceConfig, model_config: F5VietnameseConfig):
        if self.engine_factory is not None:
            return self.engine_factory()
        provider = model_config.provider.strip().lower()
        if provider == "edge_tts":
            return EdgeTtsChunkEngine(voice)
        if provider in {"f5", "f5_tts", "f5_vietnamese", "vivioice", "vivoice"}:
            identity = json.dumps({**asdict(model_config), "cache_dir": str(model_config.cache_dir)}, sort_keys=True)
            if self._engine_identity != identity:
                self.close()
                self._engine = F5VietnameseEngine(model_config)
                self._engine_identity = identity
            return self._engine
        raise TTSConfigurationError(f"Unsupported TTS_PROVIDER: {settings.tts_provider}")

    def close(self):
        if self._engine is not None:
            self._engine.close()
        self._engine = self._engine_identity = None

    def _is_cancelled(self, job_id):
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM tts_jobs WHERE id = ?", (job_id,)).fetchone()
            return row is None or row["status"] == "cancelled"

    def _synthesize_and_qa(self, engine: Any, chunk: TTSChunk, chunk_path: Path, voice: VoiceConfig, *,
                           qa_enabled=True, retry_budget=1, cancel_check=None) -> Path:
        last_result: AudioQAResult | None = None
        last_error: Exception | None = None
        for _attempt in range(retry_budget):
            if cancel_check and cancel_check():
                self.cancel_job(self._job_id_from_chunk_path(chunk_path))
                raise TTSEngineError("TTS cancelled")
            try:
                extra = {"cancel_check": cancel_check} if isinstance(engine, F5VietnameseEngine) else {}
                produced_path = Path(engine.synthesize_chunk(chunk.normalized_text, chunk_path, voice_config=voice, **extra))
                if cancel_check and cancel_check():
                    self.cancel_job(self._job_id_from_chunk_path(chunk_path))
                    raise TTSEngineError("TTS cancelled")
                qa_result = analyze_audio(produced_path, text=chunk.normalized_text) if qa_enabled else AudioQAResult(True)
                last_result = qa_result
                if qa_result.passed:
                    if qa_enabled and isinstance(engine, F5VietnameseEngine):
                        engine.confirm_audio_qa(chunk.normalized_text, voice, produced_path)
                    self._update_chunk(
                        self._job_id_from_chunk_path(chunk_path),
                        chunk.chunk_index,
                        status="completed",
                        path=produced_path,
                        duration_seconds=qa_result.duration_seconds,
                        qa_status="passed" if qa_enabled else "skipped",
                        qa_report=qa_result.to_dict() if qa_enabled else {},
                        error_message="",
                    )
                    return produced_path
                if isinstance(engine, F5VietnameseEngine):
                    engine.invalidate_audio_cache(chunk.normalized_text, voice)
                produced_path.unlink(missing_ok=True)
            except (TTSDependencyError, TTSConfigurationError):
                raise
            except Exception as exc:
                last_error = exc
                chunk_path.unlink(missing_ok=True)
        error = last_result.error if last_result else _safe_error(last_error or "TTS chunk failed")
        status = "qa_failed" if last_result is not None else "failed"
        self._update_chunk(
            self._job_id_from_chunk_path(chunk_path),
            chunk.chunk_index,
            status=status,
            duration_seconds=last_result.duration_seconds if last_result else 0,
            qa_status=status,
            qa_report=last_result.to_dict() if last_result else {},
            error_message=error,
        )
        raise TTSEngineError(error)

    def _run_legacy_fallback(
        self,
        *,
        job_id: str,
        book: dict[str, Any],
        chapter: dict[str, Any],
        text: str,
        voice: VoiceConfig,
        output_path: Path,
        report_path: Path,
        reason: BaseException,
        snapshot: dict,
        source_hash: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> TTSJobReport:
        if self.legacy_fallback is None:
            raise RuntimeError("Legacy fallback was not configured")
        self._update_job(job_id, status="running", provider="edge_tts_fallback", progress=10, error_message="")
        try:
            if self._is_cancelled(job_id) or (cancel_check and cancel_check()):
                self.cancel_job(job_id)
                return self._write_report(job_id)
            self.legacy_fallback(
                text=text,
                output_path=output_path,
                book_title=book["title"],
                chapter_number=int(chapter["chapter_number"]),
                chapter_title=chapter["title"],
                voice=None if voice.voice_id == "default" else voice.voice_id,
                rate=voice.rate,
                volume=voice.volume,
            )
            self._validate_final_output(output_path, text=text, label="chapter MP3", qa_enabled=snapshot["qa_enabled"])
            if self._is_cancelled(job_id) or (cancel_check and cancel_check()):
                self.cancel_job(job_id)
                output_path.unlink(missing_ok=True)
                return self._write_report(job_id)
            update_chapter_paths(self.db_path, int(chapter["id"]), audio_path=output_path, status="audio_done",
                expected_content_revision=snapshot["content_revision"], expected_translation_hash=source_hash,
                publication_job_id=job_id)
            retire_artifact(chapter.get("audio_path"), self.data_dir, self.db_path)
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            self._fail_job(job_id, exc)
            return self._write_report(job_id)
        now = self._now()
        with get_connection(self.db_path) as conn:
            conn.execute("DELETE FROM tts_chunks WHERE job_id = ?", (job_id,))
            conn.execute(
                """
                INSERT INTO tts_chunks
                (id, job_id, chunk_index, text, normalized_text, text_hash, start_char, end_char,
                 status, mp3_path, qa_status, qa_report_json, error_message, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?, 0, ?, 'completed', ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{job_id}:0000",
                    job_id,
                    text[:5000],
                    text[:5000],
                    text_hash(text),
                    len(text),
                    str(output_path),
                    "passed" if snapshot["qa_enabled"] else "skipped",
                    json.dumps({"fallback": "edge_tts", "reason": _safe_error(reason)}, ensure_ascii=False),
                    "",
                    now,
                    now,
                ),
            )
            conn.commit()
        self._update_job(job_id, status="completed", provider="edge_tts_fallback", progress=100, output_mp3_path=str(output_path), error_message="")
        return self._write_report(job_id, report_path=report_path)

    def _read_translated_text(self, chapter: dict[str, Any]) -> str:
        path_value = chapter.get("translated_text_path")
        if not path_value:
            return ""
        try:
            path = require_artifact_file(
                path_value,
                artifact_class=ArtifactClass.TRANSLATED,
                data_root=self.data_dir,
                old_root=getattr(self, "legacy_artifact_root", settings.artifact_legacy_root),
            )
        except ArtifactPathError:
            return ""
        return clean_translation_layout(path.read_text(encoding="utf-8"))

    def _upsert_job(
        self,
        conn,
        *,
        job_id: str,
        book_id: int,
        chapter_id: int,
        provider: str,
        model: str,
        owner_user_id: str,
        voice_hash: str,
        chapter_text_hash: str,
        report_path: Path, source_hash: str, snapshot: dict, parent_job_id: str,
    ) -> None:
        now = self._now()
        existing = conn.execute("SELECT id FROM tts_jobs WHERE id = ?", (job_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE tts_jobs
                SET status = CASE WHEN status = 'completed' THEN 'completed' ELSE 'running' END,
                    report_json_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(report_path), now, job_id),
            )
            return
        conn.execute(
            """
            INSERT INTO tts_jobs
            (id, book_id, chapter_id, status, provider, model, owner_user_id,
             voice_config_hash, text_hash, report_json_path, progress, created_at, updated_at,
             source_translation_hash, input_snapshot_json, parent_job_id)
            VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (job_id, book_id, chapter_id, provider, model, owner_user_id, voice_hash, chapter_text_hash, str(report_path), now, now, source_hash, json.dumps(snapshot, ensure_ascii=False), parent_job_id or None),
        )

    def _prepare_chunks(self, conn, job_id: str, chunks: list[TTSChunk]) -> None:
        now = self._now()
        for chunk in chunks:
            chunk_id = f"{job_id}:{chunk.chunk_index:04d}"
            current_hash = text_hash(chunk.normalized_text)
            existing = conn.execute(
                "SELECT text_hash, status FROM tts_chunks WHERE job_id = ? AND chunk_index = ?",
                (job_id, chunk.chunk_index),
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO tts_chunks
                    (id, job_id, chunk_index, text, normalized_text, text_hash, start_char,
                     end_char, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        chunk_id,
                        job_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.normalized_text,
                        current_hash,
                        chunk.start_char,
                        chunk.end_char,
                        now,
                        now,
                    ),
                )
            elif existing["text_hash"] != current_hash:
                conn.execute(
                    """
                    UPDATE tts_chunks
                    SET text = ?, normalized_text = ?, text_hash = ?, start_char = ?, end_char = ?,
                        status = 'pending', wav_path = '', mp3_path = '', duration_seconds = 0,
                        qa_status = '', qa_report_json = '{}', error_message = '', updated_at = ?
                    WHERE job_id = ? AND chunk_index = ?
                    """,
                    (
                        chunk.text,
                        chunk.normalized_text,
                        current_hash,
                        chunk.start_char,
                        chunk.end_char,
                        now,
                        job_id,
                        chunk.chunk_index,
                    ),
                )
        conn.execute("DELETE FROM tts_chunks WHERE job_id = ? AND chunk_index >= ?", (job_id, len(chunks)))

    def _get_chunk(self, job_id: str, chunk_index: int) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            return _row_to_dict(conn.execute("SELECT * FROM tts_chunks WHERE job_id = ? AND chunk_index = ?", (job_id, chunk_index)).fetchone())

    def _existing_completed_chunk_path(self, row: dict[str, Any] | None) -> Path | None:
        if not row or row.get("status") != "completed":
            return None
        for key in ("wav_path", "mp3_path"):
            path = self._resolved_output_path(row.get(key))
            if path is not None:
                return path
        return None

    def _update_chunk(
        self,
        job_id: str,
        chunk_index: int,
        *,
        status: str,
        path: Path | None = None,
        duration_seconds: float = 0,
        qa_status: str = "",
        qa_report: dict[str, Any] | None = None,
        error_message: str = "",
    ) -> None:
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, self._now()]
        if path is not None:
            if path.suffix.lower() == ".mp3":
                fields.append("mp3_path = ?")
            else:
                fields.append("wav_path = ?")
            params.append(str(path))
        if duration_seconds:
            fields.append("duration_seconds = ?")
            params.append(duration_seconds)
        if qa_status:
            fields.append("qa_status = ?")
            params.append(qa_status)
        if qa_report is not None:
            fields.append("qa_report_json = ?")
            params.append(json.dumps(qa_report, ensure_ascii=False))
        if error_message or status in {"failed", "qa_failed"}:
            fields.append("error_message = ?")
            params.append(_safe_error(error_message))
        params.extend([job_id, chunk_index])
        with get_connection(self.db_path) as conn:
            conn.execute(f"""UPDATE tts_chunks SET {', '.join(fields)}
                WHERE job_id = ? AND chunk_index = ? AND status != 'cancelled'
                AND EXISTS (SELECT 1 FROM tts_jobs WHERE id = tts_chunks.job_id AND status != 'cancelled')""", params)
            conn.commit()

    def _update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        provider: str | None = None,
        progress: int | None = None,
        output_mp3_path: str | None = None,
        output_m4b_path: str | None = None,
        error_message: str | None = None,
    ) -> None:
        fields = ["updated_at = ?"]
        params: list[Any] = [self._now()]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if provider is not None:
            fields.append("provider = ?")
            params.append(provider)
        if progress is not None:
            fields.append("progress = ?")
            params.append(max(0, min(100, int(progress))))
        if output_mp3_path is not None:
            fields.append("output_mp3_path = ?")
            params.append(output_mp3_path)
        if output_m4b_path is not None:
            fields.append("output_m4b_path = ?")
            params.append(output_m4b_path)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(_safe_error(error_message) if error_message else "")
        params.extend([job_id, status])
        with get_connection(self.db_path) as conn:
            conn.execute(f"""UPDATE tts_jobs SET {', '.join(fields)} WHERE id = ?
                AND status != 'cancelled' AND (status != 'completed' OR ? = 'completed')""", params)
            conn.commit()

    def _validate_chunk_outputs(
        self,
        job_id: str,
        chunk_artifacts: list[tuple[TTSChunk, Path]],
        *,
        expected_count: int,
    ) -> None:
        if len(chunk_artifacts) != expected_count:
            raise TTSEngineError(f"TTS job produced {len(chunk_artifacts)}/{expected_count} chunk files before merge")
        for chunk, path in chunk_artifacts:
            if not path.exists():
                error = "Chunk audio file is missing before merge"
                self._update_chunk(job_id, chunk.chunk_index, status="failed", error_message=error)
                raise TTSEngineError(error)
            if path.stat().st_size <= 0:
                path.unlink(missing_ok=True)
                error = "Chunk audio file is empty before merge"
                self._update_chunk(job_id, chunk.chunk_index, status="failed", error_message=error)
                raise TTSEngineError(error)

    def _validate_output_file(self, path: Path, label: str) -> None:
        if not path.exists():
            raise TTSEngineError(f"{label} was not created")
        if path.stat().st_size <= 0:
            path.unlink(missing_ok=True)
            raise TTSEngineError(f"{label} is empty")

    def _resolved_output_path(self, value: Any) -> Path | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            path = require_artifact_file(
                raw,
                artifact_class=ArtifactClass.AUDIO,
                data_root=self.data_dir,
                old_root=getattr(self, "legacy_artifact_root", settings.artifact_legacy_root),
            )
        except ArtifactPathError:
            return None
        if path.stat().st_size <= 0:
            return None
        return path

    def _validate_final_output(self, path: Path, *, text: str, label: str, qa_enabled=None) -> AudioQAResult:
        self._validate_output_file(path, label)
        if not (settings.tts_enable_qa if qa_enabled is None else qa_enabled):
            return AudioQAResult(True)
        result = analyze_audio(path, text=text)
        if not result.passed:
            path.unlink(missing_ok=True)
            raise TTSEngineError(result.error or f"{label} failed audio QA")
        return result

    def _build_audio_summary(self, job: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
        completed_chunks = 0
        failed_chunks = 0
        missing_chunk_files = 0
        qa_warning_count = 0
        warnings: list[str] = []
        for chunk in chunks:
            status = str(chunk.get("status") or "")
            if status == "completed":
                completed_chunks += 1
            if status in {"failed", "qa_failed"}:
                failed_chunks += 1
            if status == "completed" and self._existing_completed_chunk_path(chunk) is None:
                missing_chunk_files += 1
            qa_report = chunk.get("qa_report")
            if isinstance(qa_report, dict):
                chunk_warnings = qa_report.get("warnings")
                if isinstance(chunk_warnings, list):
                    qa_warning_count += len(
                        [warning for warning in chunk_warnings if isinstance(warning, str) and warning.strip()]
                    )

        output_mp3_path = self._resolved_output_path(job.get("output_mp3_path"))
        output_m4b_path = self._resolved_output_path(job.get("output_m4b_path"))
        output_mp3_ready = output_mp3_path is not None
        output_m4b_ready = output_m4b_path is not None
        if missing_chunk_files:
            warnings.append(f"{missing_chunk_files} completed chunk file is missing")
        if failed_chunks:
            warnings.append(f"{failed_chunks} chunk failed or needs retry")
        if qa_warning_count:
            warnings.append(f"Audio QA reported {qa_warning_count} warning(s)")
        if str(job.get("status") or "") == "completed" and not output_mp3_ready:
            warnings.append("Final chapter MP3 is missing or empty")
        if str(job.get("output_m4b_path") or "") and not output_m4b_ready:
            warnings.append("Final M4B artifact is missing or empty")

        return {
            "expected_chunk_count": len(chunks),
            "completed_chunk_count": completed_chunks,
            "failed_chunk_count": failed_chunks,
            "missing_chunk_file_count": missing_chunk_files,
            "qa_warning_count": qa_warning_count,
            "output_mp3_ready": output_mp3_ready,
            "output_mp3_size_bytes": output_mp3_path.stat().st_size if output_mp3_path is not None else 0,
            "output_m4b_ready": output_m4b_ready,
            "output_m4b_size_bytes": output_m4b_path.stat().st_size if output_m4b_path is not None else 0,
            "warnings": warnings,
        }

    def _fail_job(self, job_id: str, exc: BaseException) -> None:
        safe = _safe_error(exc)
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT status FROM tts_jobs WHERE id = ?", (job_id,)).fetchone()
        if row and str(row["status"] or "") == "cancelled":
            logger.info("TTS job %s remained cancelled after provider error: %s", job_id, safe)
            return
        logger.error("TTS job %s failed (%s)", job_id, type(exc).__name__)
        self._update_job(job_id, status="failed", error_message=safe)
        record_operational_event(
            self.db_path,
            event_type="tts_failure",
            severity="error",
            source="tts",
            message="TTS job failed",
            job_id=job_id,
            details={"reason": safe},
        )

    def _write_report(self, job_id: str, report_path: Path | None = None) -> TTSJobReport:
        job = self.get_job_status(job_id)
        if not job:
            raise ValueError("TTS job not found")
        path_value = report_path or Path(str(job.get("report_json_path") or ""))
        if path_value:
            path_value.parent.mkdir(parents=True, exist_ok=True)
            path_value.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSJobReport(
            job_id=job_id,
            status=str(job.get("status") or ""),
            book_id=int(job.get("book_id") or 0),
            chapter_id=int(job.get("chapter_id") or 0),
            output_mp3_path=str(job.get("output_mp3_path") or ""),
            output_m4b_path=str(job.get("output_m4b_path") or ""),
            report_json_path=str(path_value or ""),
            progress=int(job.get("progress") or 0),
            error_message=str(job.get("error_message") or ""),
        )

    def _job_id_from_chunk_path(self, path: Path) -> str:
        try:
            return path.parent.parent.name
        except IndexError:
            return ""

    def _decode_json(self, value: str, default: Any) -> Any:
        try:
            return json.loads(value or "")
        except json.JSONDecodeError:
            return default

    def _now(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
