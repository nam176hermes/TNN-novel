from __future__ import annotations

import math
import sqlite3
import struct
import wave
from pathlib import Path

import pytest

from app.database.db import add_book, add_chapter, get_chapter_by_id, init_db, update_chapter_paths
from app.services.tts.f5_vietnamese_engine import VoiceConfig
from app.services.tts.tts_pipeline import EdgeTtsChunkEngine, TTSPipeline


def _write_wav(path: Path, *, duration_seconds: float = 0.25) -> None:
    sample_rate = 24000
    frames = int(sample_rate * duration_seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        payload = bytearray()
        for index in range(frames):
            payload.extend(struct.pack("<h", int(math.sin(index / 10) * 8000)))
        wav.writeframes(bytes(payload))


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        self.calls += 1
        _write_wav(output_path)
        return output_path


class ExplodingEngine:
    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        raise AssertionError("resume should not synthesize completed chunks")


def _prepare_translated_chapter(db_path: Path, tmp_path: Path) -> tuple[int, int]:
    init_db(db_path)
    book_id = add_book(db_path, "Độc Tu", author="Thủy Đạo Bất Cô")
    chapter_id = add_chapter(db_path, book_id, 1, "Chương 1")
    translation_path = tmp_path / "chapter-1.txt"
    translation_path.write_text(
        "Chương 1. Đây là một đoạn tiếng Việt để tạo audio. "
        "Nhân vật bước vào động phủ. Hắn khẽ nói rằng mọi chuyện đã ổn.",
        encoding="utf-8",
    )
    update_chapter_paths(db_path, chapter_id, translated_text_path=translation_path, status="translated")
    return book_id, chapter_id


def test_tts_tables_exist_after_initialization(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    with sqlite3.connect(temp_db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"tts_jobs", "tts_chunks"}.issubset(tables)


def test_tts_pipeline_generates_report_and_updates_chapter_audio(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    engine = FakeEngine()

    def fake_merge(chunk_paths, output_path, **kwargs):
        assert chunk_paths
        output_path.write_bytes(b"fake mp3")
        return output_path

    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_chapter_audio", fake_merge)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 70)
    pipeline = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: engine)

    report = pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="tts-test")

    assert report.status == "completed"
    assert report.progress == 100
    assert report.error_message == ""
    assert Path(report.output_mp3_path).read_bytes() == b"fake mp3"
    chapter = get_chapter_by_id(temp_db_path, chapter_id)
    assert chapter is not None
    assert chapter["audio_path"] == report.output_mp3_path
    status = pipeline.get_job_status("tts-test")
    assert status is not None
    assert status["error_message"] == ""
    assert status["chunks"]
    assert all(chunk["status"] == "completed" for chunk in status["chunks"])


def test_tts_pipeline_resume_reuses_completed_chunks(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)

    def fake_merge(chunk_paths, output_path, **kwargs):
        output_path.write_bytes(b"fake mp3")
        return output_path

    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_chapter_audio", fake_merge)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 70)
    first_engine = FakeEngine()
    TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: first_engine).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-resume",
    )

    report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: ExplodingEngine()).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-resume",
        resume=True,
    )

    assert report.status == "completed"
    assert first_engine.calls > 0


def test_tts_pipeline_cancel_after_last_chunk_does_not_merge_audio(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    engine = FakeEngine()
    checks = iter([False, True])
    merge_called = False

    def fake_merge(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal merge_called
        merge_called = True
        raise AssertionError("cancelled TTS job should not merge audio")

    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_chapter_audio", fake_merge)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 10_000)

    report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: engine).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-cancel-before-merge",
        cancel_check=lambda: next(checks, True),
    )

    assert report.status == "cancelled"
    assert not merge_called


def test_completed_tts_status_hides_stale_error_message(temp_db_path: Path, tmp_path: Path) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    now = "2026-07-01T00:00:00+00:00"

    with sqlite3.connect(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO tts_jobs
            (id, book_id, chapter_id, status, provider, model, progress, error_message, created_at, updated_at)
            VALUES ('tts-stale-error', ?, ?, 'completed', 'f5_vietnamese', 'vivioice', 100, 'TTS failed. Check server logs.', ?, ?)
            """,
            (book_id, chapter_id, now, now),
        )
        conn.commit()

    status = TTSPipeline(temp_db_path, tmp_path).get_job_status("tts-stale-error")

    assert status is not None
    assert status["status"] == "completed"
    assert status["error_message"] == ""


@pytest.mark.asyncio
async def test_edge_tts_chunk_engine_is_safe_inside_running_event_loop(tmp_path: Path, monkeypatch) -> None:
    class FakeCommunicate:
        def __init__(self, text: str, voice: str, *, rate: str, volume: str) -> None:
            self.text = text
            self.voice = voice
            self.rate = rate
            self.volume = volume

        async def save(self, output_path: str) -> None:
            Path(output_path).write_bytes(b"fake audio")

    monkeypatch.setattr("app.services.tts.tts_pipeline.edge_tts.Communicate", FakeCommunicate)
    output_path = tmp_path / "chunk.mp3"
    engine = EdgeTtsChunkEngine(VoiceConfig())

    produced = engine.synthesize_chunk("Xin chào.", output_path, voice_config=VoiceConfig())

    assert produced == output_path
    assert output_path.read_bytes() == b"fake audio"
