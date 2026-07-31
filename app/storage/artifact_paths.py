from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import logging
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


class ArtifactClass(StrEnum):
    RAW = "raw"
    CLEANED = "cleaned"
    TRANSLATED = "translated"
    HTML = "html"
    COVER = "cover"
    AUDIO = "audio"
    TTS_REPORT = "tts_report"
    TTS_CHUNK = "tts_chunk"


class ResolutionStatus(StrEnum):
    CURRENT = "current"
    REMAPPED = "remapped"
    METADATA_MISSING = "metadata_missing"
    FILE_MISSING = "file_missing"
    OUTSIDE_ALLOWED_ROOT = "outside_allowed_root"
    WRONG_TYPE = "wrong_type"


@dataclass(frozen=True)
class PathField:
    table: str
    primary_key: str
    column: str
    artifact_class: ArtifactClass
    active_where: str = "1 = 1"


@dataclass(frozen=True)
class ArtifactResolution:
    status: ResolutionStatus
    path: Path | None = None
    relative_suffix: Path | None = None
    reason: str = ""


APPROVED_PATH_FIELDS: tuple[PathField, ...] = (
    PathField("books", "id", "cover_path", ArtifactClass.COVER),
    PathField("chapters", "id", "raw_text_path", ArtifactClass.RAW, "deleted_at IS NULL"),
    PathField("chapters", "id", "cleaned_text_path", ArtifactClass.CLEANED, "deleted_at IS NULL"),
    PathField("chapters", "id", "translated_text_path", ArtifactClass.TRANSLATED, "deleted_at IS NULL"),
    PathField("chapters", "id", "content_html_path", ArtifactClass.HTML, "deleted_at IS NULL"),
    PathField("chapters", "id", "audio_path", ArtifactClass.AUDIO, "deleted_at IS NULL"),
    PathField("tts_jobs", "id", "output_mp3_path", ArtifactClass.AUDIO),
    PathField("tts_jobs", "id", "output_m4b_path", ArtifactClass.AUDIO),
    PathField("tts_jobs", "id", "report_json_path", ArtifactClass.TTS_REPORT),
    PathField("tts_chunks", "id", "wav_path", ArtifactClass.TTS_CHUNK),
    PathField("tts_chunks", "id", "mp3_path", ArtifactClass.TTS_CHUNK),
)


logger = logging.getLogger(__name__)


_SAFE_ERROR_MESSAGES: dict[ResolutionStatus, str] = {
    ResolutionStatus.METADATA_MISSING: "Artifact metadata missing",
    ResolutionStatus.FILE_MISSING: "Artifact file missing",
    ResolutionStatus.OUTSIDE_ALLOWED_ROOT: "Artifact path outside allowed root",
    ResolutionStatus.WRONG_TYPE: "Artifact path is not a file",
}


class ArtifactPathError(RuntimeError):
    def __init__(self, status: ResolutionStatus):
        self.status = status
        super().__init__(_SAFE_ERROR_MESSAGES.get(status, "Artifact path unavailable"))


@lru_cache(maxsize=len(ArtifactClass))
def _warn_legacy_resolution_once(artifact_class: ArtifactClass) -> None:
    logger.warning(
        "Resolved exact configured legacy artifact prefix for class=%s; remove compatibility after P0A apply",
        artifact_class.value,
    )


def _normalized_text(value: str | Path) -> str:
    return str(value).replace("\\", "/").rstrip("/")


def _is_url(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.scheme or parsed.netloc)


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _result_for_candidate(
    candidate: Path,
    *,
    data_root: Path,
    allowed_root: Path,
    success_status: ResolutionStatus,
    require_exists: bool,
) -> ArtifactResolution:
    resolved = candidate.resolve(strict=False)
    if not _is_contained(resolved, allowed_root):
        return ArtifactResolution(
            ResolutionStatus.OUTSIDE_ALLOWED_ROOT,
            reason="resolved path is outside the allowed artifact root",
        )

    relative_suffix = resolved.relative_to(data_root)
    if require_exists and not resolved.exists():
        return ArtifactResolution(
            ResolutionStatus.FILE_MISSING,
            path=resolved,
            relative_suffix=relative_suffix,
            reason="artifact file does not exist",
        )
    if require_exists and not resolved.is_file():
        return ArtifactResolution(
            ResolutionStatus.WRONG_TYPE,
            path=resolved,
            relative_suffix=relative_suffix,
            reason="artifact metadata points to a non-file target",
        )
    return ArtifactResolution(success_status, path=resolved, relative_suffix=relative_suffix)


def resolve_artifact_path(
    value: str | Path | None,
    *,
    artifact_class: ArtifactClass,
    data_root: Path,
    old_root: Path | None = None,
    require_exists: bool = False,
) -> ArtifactResolution:
    """Resolve one known artifact class without accepting arbitrary filesystem paths."""

    if value is None or not str(value).strip():
        return ArtifactResolution(
            ResolutionStatus.METADATA_MISSING,
            reason="artifact path metadata is blank",
        )

    normalized_value = _normalized_text(str(value).strip())
    if _is_url(normalized_value):
        return ArtifactResolution(
            ResolutionStatus.OUTSIDE_ALLOWED_ROOT,
            reason="URLs are not filesystem artifact paths",
        )

    resolved_data_root = data_root.resolve(strict=False)
    allowed_root = resolved_data_root

    if old_root is not None:
        normalized_old_root = _normalized_text(old_root)
        if normalized_value == normalized_old_root or normalized_value.startswith(normalized_old_root + "/"):
            relative_text = normalized_value[len(normalized_old_root) :].lstrip("/")
            relative_parts = PurePosixPath(relative_text).parts
            if relative_parts and relative_parts[0] == "data":
                relative_parts = relative_parts[1:]
            if not relative_parts or ".." in relative_parts:
                return ArtifactResolution(
                    ResolutionStatus.OUTSIDE_ALLOWED_ROOT,
                    reason="legacy path suffix is empty or contains traversal",
                )
            candidate = resolved_data_root.joinpath(*relative_parts)
            return _result_for_candidate(
                candidate,
                data_root=resolved_data_root,
                allowed_root=allowed_root,
                success_status=ResolutionStatus.REMAPPED,
                require_exists=require_exists,
            )

    candidate = Path(normalized_value)
    if not candidate.is_absolute():
        relative_parts = PurePosixPath(normalized_value).parts
        if ".." in relative_parts:
            return ArtifactResolution(
                ResolutionStatus.OUTSIDE_ALLOWED_ROOT,
                reason="relative path contains traversal",
            )
        candidate = resolved_data_root.joinpath(*relative_parts)

    return _result_for_candidate(
        candidate,
        data_root=resolved_data_root,
        allowed_root=allowed_root,
        success_status=ResolutionStatus.CURRENT,
        require_exists=require_exists,
    )


def require_artifact_file(
    value: str | Path | None,
    *,
    artifact_class: ArtifactClass,
    data_root: Path,
    old_root: Path | None = None,
) -> Path:
    resolution = resolve_artifact_path(
        value,
        artifact_class=artifact_class,
        data_root=data_root,
        old_root=old_root,
        require_exists=True,
    )
    if resolution.status is ResolutionStatus.REMAPPED:
        _warn_legacy_resolution_once(artifact_class)
    if resolution.status not in {ResolutionStatus.CURRENT, ResolutionStatus.REMAPPED} or resolution.path is None:
        raise ArtifactPathError(resolution.status)
    return resolution.path
