from __future__ import annotations

import pytest

from app.jobs import batch


@pytest.mark.asyncio
async def test_local_batch_translate_command_starts_and_waits_without_web_login(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeService:
        kwargs: dict | None = None

        def start_translate_job(self, **kwargs) -> str:
            self.kwargs = kwargs
            return "job-translate"

        def get_job_status(self, job_id: str) -> dict:
            assert job_id == "job-translate"
            return {
                "job_id": job_id,
                "status": "completed",
                "progress": 3,
                "total": 3,
                "message": "Job completed",
            }

    service = FakeService()
    monkeypatch.setattr(batch, "_service", lambda: service)
    args = batch.build_parser().parse_args(
        [
            "translate",
            "--book-id",
            "7",
            "--limit",
            "25",
            "--preset-id",
            "fast_draft",
            "--style-profile-id",
            "huyen_huyen",
            "--chunk-size",
            "3500",
        ]
    )

    result = await batch.run(args)

    assert result == 0
    assert service.kwargs == {
        "book_id": 7,
        "chapter_ids": [],
        "limit": 25,
        "preset_id": "fast_draft",
        "style_profile_id": "huyen_huyen",
        "chunk_size": 3500,
    }
    assert "job_id=job-translate" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_local_batch_tts_command_returns_failure_for_failed_job(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeService:
        kwargs: dict | None = None

        def start_tts_job(self, **kwargs) -> str:
            self.kwargs = kwargs
            return "job-tts"

        def get_job_status(self, job_id: str) -> dict:
            assert job_id == "job-tts"
            return {
                "job_id": job_id,
                "status": "failed",
                "progress": 1,
                "total": 2,
                "message": "TTS failed",
                "error": "TTS failed. Check server logs.",
            }

    service = FakeService()
    monkeypatch.setattr(batch, "_service", lambda: service)
    args = batch.build_parser().parse_args(
        [
            "tts",
            "--book-id",
            "7",
            "--limit",
            "40",
            "--voice",
            "vi-VN-HoaiMyNeural",
            "--rate=-10%",
            "--volume",
            "+5%",
        ]
    )

    result = await batch.run(args)

    assert result == 1
    assert service.kwargs == {
        "book_id": 7,
        "chapter_ids": [],
        "limit": 40,
        "voice": "vi-VN-HoaiMyNeural",
        "rate": "-10%",
        "volume": "+5%",
    }
    assert "error=TTS failed. Check server logs." in capsys.readouterr().out
