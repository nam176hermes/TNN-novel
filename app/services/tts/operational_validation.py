from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


_SAFE_TAG_KEYS = {
    "album",
    "artist",
    "comment",
    "composer",
    "date",
    "description",
    "encoder",
    "genre",
    "language",
    "narrator",
    "title",
}


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def redact_validation_text(value: object, *, max_len: int = 500) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)=?[^\s,;]+", r"\1=[redacted]", text)
    text = re.sub(r"(?i)(authorization:?\s*bearer\s+)[^\s,;]+", r"\1[redacted]", text)
    text = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", text)
    text = re.sub(r"(/[A-Za-z0-9._~+\-]+){2,}", "[path]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def validate_chapter_marker_order(chapters: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    last_start = -1.0
    last_end = -1.0
    for index, chapter in enumerate(chapters):
        try:
            start = float(chapter.get("start_time") or 0)
            end = float(chapter.get("end_time") or 0)
        except (TypeError, ValueError):
            warnings.append(f"Chapter marker {index + 1} has invalid timestamps")
            continue
        if end <= start:
            warnings.append(f"Chapter marker {index + 1} has non-positive duration")
        if start < last_start:
            warnings.append(f"Chapter marker {index + 1} starts before the previous marker")
        if start < last_end:
            warnings.append(f"Chapter marker {index + 1} overlaps the previous marker")
        last_start = start
        last_end = end
    return warnings


def inspect_media_artifact(
    path: Path,
    *,
    include_chapters: bool = True,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.name),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
        "format_name": "",
        "duration_seconds": 0.0,
        "bit_rate": 0,
        "tags": {},
        "chapter_count": 0,
        "chapters": [],
        "warnings": [],
        "error": "",
        "ffprobe_available": ffprobe_available(),
    }
    if not result["exists"]:
        result["error"] = "Artifact does not exist"
        return result
    if result["size_bytes"] <= 0:
        result["error"] = "Artifact is empty"
        return result
    if not result["ffprobe_available"]:
        result["warnings"].append("ffprobe unavailable; metadata and duration inspection skipped")
        return result

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        result["warnings"].append("ffprobe unavailable; metadata and duration inspection skipped")
        return result

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration,bit_rate:format_tags:chapters",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result["error"] = redact_validation_text(exc)
        return result

    if completed.returncode != 0:
        result["error"] = redact_validation_text(completed.stderr or completed.stdout or "ffprobe failed")
        return result

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        result["error"] = redact_validation_text(exc)
        return result

    format_payload = payload.get("format") or {}
    result["format_name"] = str(format_payload.get("format_name") or "")
    try:
        result["duration_seconds"] = round(float(format_payload.get("duration") or 0), 3)
    except (TypeError, ValueError):
        result["duration_seconds"] = 0.0
    try:
        result["bit_rate"] = int(float(format_payload.get("bit_rate") or 0))
    except (TypeError, ValueError):
        result["bit_rate"] = 0

    raw_tags = format_payload.get("tags") or {}
    result["tags"] = {
        str(key): str(value)
        for key, value in raw_tags.items()
        if str(key).lower() in _SAFE_TAG_KEYS and str(value).strip()
    }

    raw_chapters = payload.get("chapters") or []
    if include_chapters and raw_chapters:
        chapters: list[dict[str, Any]] = []
        for chapter in raw_chapters:
            tags = chapter.get("tags") or {}
            chapter_entry = {
                "id": str(chapter.get("id") or ""),
                "start_time": float(chapter.get("start_time") or 0),
                "end_time": float(chapter.get("end_time") or 0),
                "title": str(tags.get("title") or ""),
            }
            chapters.append(chapter_entry)
        result["chapters"] = chapters
        result["chapter_count"] = len(chapters)
        result["warnings"].extend(validate_chapter_marker_order(chapters))
    elif include_chapters:
        result["warnings"].append("No chapter markers detected")

    return result
