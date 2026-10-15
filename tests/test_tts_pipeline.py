from __future__ import annotations

import math
import sqlite3
import struct
import wave
from pathlib import Path

import pytest

from app.database.db import add_book, add_chapter, get_chapter_by_id, init_db, update_chapter_paths
import app.services.tts.tts_pipeline as tts_pipeline_module
from app.services.tts.availability import TTSUnavailableError
from app.services.tts.f5_vietnamese_engine import TTSEngineError, VoiceConfig
from app.services.tts.tts_pipeline import EdgeTtsChunkEngine, TTSPipeline
from app.services.tts.audio_qa import AudioQAResult


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


@pytest.fixture(autouse=True)
def allow_injected_tts_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_pipeline_module, "require_tts_runtime_available", lambda **kwargs: None, raising=False)


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


class FailSecondChunkEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        self.calls.append(normalized_text)
        if len(self.calls) >= 2:
            raise RuntimeError("provider timeout")
        _write_wav(output_path)
        return output_path


class RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        self.calls.append(normalized_text)
        _write_wav(output_path)
        return output_path


class PartialOutputTimeoutEngine:
    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        output_path.write_bytes(b"partial")
        raise RuntimeError("provider timeout")


class EmptyOutputEngine:
    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        output_path.write_bytes(b"")
        return output_path


class CancellingErrorEngine:
    def __init__(self, pipeline: TTSPipeline, job_id: str) -> None:
        self.pipeline = pipeline
        self.job_id = job_id

    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        self.pipeline.cancel_job(self.job_id)
        raise RuntimeError("provider timeout after cancellation")


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


def _patch_final_mp3_qa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.tts.tts_pipeline.analyze_audio",
        lambda path, **kwargs: AudioQAResult(True, duration_seconds=1.0),
    )


def test_tts_tables_exist_after_initialization(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    with sqlite3.connect(temp_db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"tts_jobs", "tts_chunks"}.issubset(tables)


def test_direct_f5_pipeline_rejects_unavailable_runtime_before_writing_job_state(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    monkeypatch.setattr(tts_pipeline_module.settings, "tts_provider", "f5_vietnamese")

    def reject_unavailable_runtime(*, provider: str) -> None:
        raise TTSUnavailableError("Local F5 TTS is unavailable: a CUDA GPU is required.")

    pipeline = TTSPipeline(temp_db_path, tmp_path)
    monkeypatch.setattr(
        tts_pipeline_module,
        "require_tts_runtime_available",
        reject_unavailable_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_engine",
        lambda *args, **kwargs: pytest.fail("The F5 engine must not be built"),
    )

    with pytest.raises(TTSUnavailableError):
        pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="tts-unavailable")

    with sqlite3.connect(temp_db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tts_jobs").fetchone()[0] == 0
    assert not (tmp_path / "audio" / "tts_jobs" / "tts-unavailable").exists()


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

    _patch_final_mp3_qa(monkeypatch)
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

    _patch_final_mp3_qa(monkeypatch)
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


def test_tts_input_change_during_inference_cannot_publish(temp_db_path, tmp_path, monkeypatch):
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    _patch_final_mp3_qa(monkeypatch)
    monkeypatch.setattr(tts_pipeline_module, "merge_chapter_audio", lambda paths, output, **kw: output.write_bytes(b"new audio"))
    class EditingEngine(FakeEngine):
        def synthesize_chunk(self, *args, **kwargs):
            result = super().synthesize_chunk(*args, **kwargs)
            changed = tmp_path / "new-translation.txt"
            changed.write_text("Bản dịch mới phải giữ nguyên.", encoding="utf-8")
            update_chapter_paths(temp_db_path, chapter_id, translated_text_path=changed)
            return result
    report = TTSPipeline(temp_db_path, tmp_path, engine_factory=EditingEngine).generate_chapter(
        book_id=book_id, chapter_id=chapter_id, job_id="tts-stale-input")
    assert report.status == "failed"
    assert not get_chapter_by_id(temp_db_path, chapter_id)["audio_path"]


def test_tts_resume_rejects_a_changed_voice_and_preserves_manifest(temp_db_path, tmp_path, monkeypatch):
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    _patch_final_mp3_qa(monkeypatch)
    monkeypatch.setattr(tts_pipeline_module, "merge_chapter_audio", lambda paths, output, **kw: output.write_bytes(b"audio"))
    pipeline = TTSPipeline(temp_db_path, tmp_path, engine_factory=FakeEngine)
    pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="tts-voice", voice_config={"voice_id": "one"})
    before = pipeline.get_job_status("tts-voice")
    with pytest.raises(ValueError, match="input.*changed"):
        pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="tts-voice", voice_config={"voice_id": "two"})
    assert pipeline.get_job_status("tts-voice")["voice_config_hash"] == before["voice_config_hash"]


def test_tts_pipeline_retry_failed_chunks_only_regenerates_failed_chunks(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)

    def fake_merge(chunk_paths, output_path, **kwargs):
        output_path.write_bytes(b"fake mp3")
        return output_path

    _patch_final_mp3_qa(monkeypatch)
    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_chapter_audio", fake_merge)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 35)

    first_engine = FailSecondChunkEngine()
    first_report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: first_engine).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-retry-failed-chunks",
    )

    assert first_report.status == "failed"
    failed_status = TTSPipeline(temp_db_path, tmp_path).get_job_status("tts-retry-failed-chunks")
    assert failed_status is not None
    assert [chunk["status"] for chunk in failed_status["chunks"]].count("completed") >= 1
    assert [chunk["status"] for chunk in failed_status["chunks"]].count("failed") == 1

    retry_engine = RecordingEngine()
    retry_report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: retry_engine).retry_failed_chunks(
        "tts-retry-failed-chunks",
    )

    assert retry_report.status == "completed"
    assert len(retry_engine.calls) == 1


def test_tts_pipeline_cleans_partial_chunk_file_after_timeout(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 10_000)

    report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: PartialOutputTimeoutEngine()).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-partial-timeout",
    )

    assert report.status == "failed"
    chunk_path = tmp_path / "audio" / "tts_jobs" / "tts-partial-timeout" / "chunks" / "chunk_0000.wav"
    assert not chunk_path.exists()


def test_tts_pipeline_marks_zero_byte_provider_output_as_failed(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 10_000)

    report = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: EmptyOutputEngine()).generate_chapter(
        book_id=book_id,
        chapter_id=chapter_id,
        job_id="tts-empty-chunk-output",
    )

    assert report.status == "failed"
    status = TTSPipeline(temp_db_path, tmp_path).get_job_status("tts-empty-chunk-output")
    assert status is not None
    assert status["chunks"][0]["status"] == "qa_failed"
    assert "empty" in str(status["chunks"][0]["error_message"]).lower()


def test_tts_pipeline_preserves_cancelled_state_when_provider_errors_after_cancel(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    monkeypatch.setattr("app.services.tts.tts_pipeline.settings.tts_chunk_max_chars", 10_000)
    job_id = "tts-cancelled-provider-error"
    pipeline: TTSPipeline
    pipeline = TTSPipeline(
        temp_db_path,
        tmp_path,
        engine_factory=lambda: CancellingErrorEngine(pipeline, job_id),
    )

    report = pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id=job_id)

    assert report.status == "cancelled"
    status = pipeline.get_job_status(job_id)
    assert status is not None
    assert status["status"] == "cancelled"


def test_cancellation_at_progress_callback_blocks_merge_and_late_updates(temp_db_path, tmp_path, monkeypatch):
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    pipeline = TTSPipeline(temp_db_path, tmp_path, engine_factory=FakeEngine)
    monkeypatch.setattr(tts_pipeline_module, "merge_chapter_audio", lambda *_args, **_kwargs: pytest.fail("cancelled job merged"))
    report = pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="cancel-progress",
        progress_callback=lambda *_: pipeline.cancel_job("cancel-progress"))
    pipeline._update_job("cancel-progress", status="running", progress=99)
    pipeline._update_chunk("cancel-progress", 0, status="running")
    assert report.status == pipeline.get_job_status("cancel-progress")["status"] == "cancelled"
    assert pipeline.get_job_status("cancel-progress")["chunks"][0]["status"] == "completed"
    assert not get_chapter_by_id(temp_db_path, chapter_id)["audio_path"]


def test_engine_start_failure_is_recorded_without_publishing(temp_db_path, tmp_path):
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    def unavailable():
        raise tts_pipeline_module.TTSDependencyError("test dependency unavailable")
    pipeline = TTSPipeline(temp_db_path, tmp_path, engine_factory=unavailable)
    report = pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="engine-start-error")
    assert report.status == "failed"
    assert not get_chapter_by_id(temp_db_path, chapter_id)["audio_path"]


def test_tts_pipeline_audio_summary_flags_missing_completed_chunk_files(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)

    def fake_merge(chunk_paths, output_path, **kwargs):
        output_path.write_bytes(b"fake mp3")
        return output_path

    _patch_final_mp3_qa(monkeypatch)
    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_chapter_audio", fake_merge)
    pipeline = TTSPipeline(temp_db_path, tmp_path, engine_factory=lambda: FakeEngine())
    pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id="tts-audio-summary")
    status = pipeline.get_job_status("tts-audio-summary")
    assert status is not None
    first_chunk_path = Path(status["chunks"][0]["wav_path"])
    first_chunk_path.unlink()

    refreshed = pipeline.get_job_status("tts-audio-summary")

    assert refreshed is not None
    assert refreshed["audio_summary"]["missing_chunk_file_count"] == 1
    assert "1 completed chunk file is missing" in refreshed["audio_summary"]["warnings"]


def test_tts_pipeline_get_download_path_rejects_zero_byte_outputs(temp_db_path: Path, tmp_path: Path) -> None:
    book_id, chapter_id = _prepare_translated_chapter(temp_db_path, tmp_path)
    empty_output = tmp_path / "empty.mp3"
    empty_output.write_bytes(b"")
    now = "2026-07-01T00:00:00+00:00"

    with sqlite3.connect(temp_db_path) as conn:
        conn.execute(
            """
            INSERT INTO tts_jobs
            (id, book_id, chapter_id, status, provider, model, progress, output_mp3_path, created_at, updated_at)
            VALUES ('tts-empty-output', ?, ?, 'completed', 'f5_vietnamese', 'vivioice', 100, ?, ?, ?)
            """,
            (book_id, chapter_id, str(empty_output), now, now),
        )
        conn.commit()

    assert TTSPipeline(temp_db_path, tmp_path).get_download_path("tts-empty-output") is None


def test_generate_book_m4b_rejects_empty_artifact(
    temp_db_path: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    init_db(temp_db_path)
    book_id = add_book(temp_db_path, "Audio book", author="Author")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chapter 1")
    audio_path = tmp_path / "chapter.mp3"
    audio_path.write_bytes(b"chapter audio")
    update_chapter_paths(temp_db_path, chapter_id, audio_path=audio_path, status="audio_done")

    def fake_merge_book_m4b(chapter_paths, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"")
        return output_path

    monkeypatch.setattr("app.services.tts.tts_pipeline.merge_book_m4b", fake_merge_book_m4b)

    with pytest.raises(TTSEngineError, match="book M4B is empty"):
        TTSPipeline(temp_db_path, tmp_path).generate_book_m4b(book_id, job_id="m4b-empty")


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
