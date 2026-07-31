from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.artifact_paths import (
    APPROVED_PATH_FIELDS,
    ArtifactClass,
    ResolutionStatus,
    resolve_artifact_path,
)


OLD_ROOT = Path("/home/thenam176/novel_pipeline")


def test_exact_old_root_is_remapped_to_configured_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    target = data_root / "raw" / "book" / "chapter.txt"
    target.parent.mkdir(parents=True)
    target.write_text("fixture", encoding="utf-8")

    result = resolve_artifact_path(
        "/home/thenam176/novel_pipeline/data/raw/book/chapter.txt",
        artifact_class=ArtifactClass.RAW,
        data_root=data_root,
        old_root=OLD_ROOT,
        require_exists=True,
    )

    assert result.status is ResolutionStatus.REMAPPED
    assert result.path == target.resolve()
    assert result.relative_suffix == Path("raw/book/chapter.txt")


@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_path_is_rejected_before_path_construction(value: str | None, tmp_path: Path) -> None:
    result = resolve_artifact_path(value, artifact_class=ArtifactClass.RAW, data_root=tmp_path)

    assert result.status is ResolutionStatus.METADATA_MISSING
    assert result.path is None


def test_current_root_path_is_unchanged_and_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "data" / "translated" / "chapter.txt"
    target.parent.mkdir(parents=True)
    target.write_text("fixture", encoding="utf-8")

    first = resolve_artifact_path(
        str(target),
        artifact_class=ArtifactClass.TRANSLATED,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
        require_exists=True,
    )
    second = resolve_artifact_path(
        str(first.path),
        artifact_class=ArtifactClass.TRANSLATED,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
        require_exists=True,
    )

    assert first.status is ResolutionStatus.CURRENT
    assert second.status is ResolutionStatus.CURRENT
    assert second.path == first.path


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/chapter.txt",
        "file:///tmp/chapter.txt",
        "/etc/passwd",
        "C:\\private\\chapter.txt",
    ],
)
def test_url_and_unrelated_absolute_paths_are_rejected(value: str, tmp_path: Path) -> None:
    result = resolve_artifact_path(
        value,
        artifact_class=ArtifactClass.RAW,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
    )

    assert result.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT
    assert result.path is None


def test_old_root_traversal_is_rejected(tmp_path: Path) -> None:
    result = resolve_artifact_path(
        "/home/thenam176/novel_pipeline/data/raw/../../outside.txt",
        artifact_class=ArtifactClass.RAW,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
    )

    assert result.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT
    assert result.path is None


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    raw_root = data_root / "raw"
    raw_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (raw_root / "escape").symlink_to(outside, target_is_directory=True)
    (outside / "chapter.txt").write_text("fixture", encoding="utf-8")

    result = resolve_artifact_path(
        str(raw_root / "escape" / "chapter.txt"),
        artifact_class=ArtifactClass.RAW,
        data_root=data_root,
        old_root=OLD_ROOT,
        require_exists=True,
    )

    assert result.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT
    assert result.path is None


def test_directory_is_not_accepted_for_file_artifact(tmp_path: Path) -> None:
    target = tmp_path / "data" / "covers" / "not-a-file.jpg"
    target.mkdir(parents=True)

    result = resolve_artifact_path(
        str(target),
        artifact_class=ArtifactClass.COVER,
        data_root=tmp_path / "data",
        require_exists=True,
    )

    assert result.status is ResolutionStatus.WRONG_TYPE
    assert result.path == target.resolve()


def test_missing_file_remains_missing_without_guessing(tmp_path: Path) -> None:
    result = resolve_artifact_path(
        "/home/thenam176/novel_pipeline/data/audio/missing.mp3",
        artifact_class=ArtifactClass.AUDIO,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
        require_exists=True,
    )

    assert result.status is ResolutionStatus.FILE_MISSING
    assert result.path == (tmp_path / "data" / "audio" / "missing.mp3").resolve()


def test_windows_separators_in_exact_old_root_are_normalized(tmp_path: Path) -> None:
    target = tmp_path / "data" / "audio" / "chapter.mp3"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"audio")

    result = resolve_artifact_path(
        "\\home\\thenam176\\novel_pipeline\\data\\audio\\chapter.mp3",
        artifact_class=ArtifactClass.AUDIO,
        data_root=tmp_path / "data",
        old_root=OLD_ROOT,
        require_exists=True,
    )

    assert result.status is ResolutionStatus.REMAPPED
    assert result.path == target.resolve()


def test_registry_contains_only_known_active_path_fields() -> None:
    fields = {(field.table, field.column) for field in APPROVED_PATH_FIELDS}

    assert fields == {
        ("books", "cover_path"),
        ("chapters", "raw_text_path"),
        ("chapters", "cleaned_text_path"),
        ("chapters", "translated_text_path"),
        ("chapters", "content_html_path"),
        ("chapters", "audio_path"),
        ("tts_jobs", "output_mp3_path"),
        ("tts_jobs", "output_m4b_path"),
        ("tts_jobs", "report_json_path"),
        ("tts_chunks", "wav_path"),
        ("tts_chunks", "mp3_path"),
    }
