from __future__ import annotations

from pathlib import Path

from app.services.tts.operational_validation import (
    inspect_media_artifact,
    redact_validation_text,
    validate_chapter_marker_order,
)


def test_redact_validation_text_masks_secret_and_path() -> None:
    value = "api_key=abc123 Authorization: Bearer token456 /tmp/private/file.mp3"
    redacted = redact_validation_text(value)

    assert "abc123" not in redacted
    assert "token456" not in redacted
    assert "/tmp/private/file.mp3" not in redacted
    assert "[redacted]" in redacted
    assert "[path]" in redacted


def test_validate_chapter_marker_order_flags_invalid_sequences() -> None:
    warnings = validate_chapter_marker_order(
        [
            {"start_time": 0.0, "end_time": 5.0, "title": "One"},
            {"start_time": 4.5, "end_time": 9.0, "title": "Two"},
            {"start_time": 3.0, "end_time": 2.0, "title": "Broken"},
        ]
    )

    assert any("overlaps" in item.lower() for item in warnings)
    assert any("non-positive duration" in item.lower() for item in warnings)


def test_inspect_media_artifact_handles_missing_file_safely(tmp_path: Path) -> None:
    result = inspect_media_artifact(tmp_path / "missing.m4b")

    assert result["exists"] is False
    assert result["error"] == "Artifact does not exist"
    assert result["path"] == "missing.m4b"
