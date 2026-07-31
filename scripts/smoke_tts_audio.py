from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import wave
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

import httpx

from app.config import PROJECT_ROOT, settings
from app.database.db import (
    add_book,
    add_chapter,
    get_book_by_id,
    get_chapter_by_id,
    get_qa_report,
    init_db,
    list_chapters,
    update_chapter_paths,
)
from app.services.tts.audio_merger import AudioMetadata, ensure_ffmpeg, merge_book_m4b
from app.services.tts.audio_qa import ffprobe_available
from app.services.tts.chunker import chunk_text
from app.services.tts.f5_vietnamese_engine import VoiceConfig
from app.services.tts.operational_validation import inspect_media_artifact, redact_validation_text
from app.services.tts.text_normalizer import normalize_text
from app.services.tts.tts_pipeline import TTSPipeline
from app.translation.idiom_correction import clean_translation_layout


DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "tts-validation"


def _write_fixture_wav(path: Path, *, duration_seconds: float = 0.35) -> None:
    sample_rate = 24000
    frames = int(sample_rate * duration_seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x01\x08" * frames)


class FixtureEngine:
    def synthesize_chunk(self, normalized_text: str, output_path: Path, *, voice_config) -> Path:
        _write_fixture_wav(output_path)
        return output_path


@dataclass
class SmokeResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChapterPlan:
    chapter_id: int
    chapter_number: int
    title: str
    translated_path: str
    char_count: int
    chunk_count: int
    has_audio: bool
    qa_status: str
    chinese_leakage_count: int
    warnings: list[str] = field(default_factory=list)


def _pass(message: str, **details: Any) -> SmokeResult:
    print(f"PASS {message}")
    return SmokeResult(True, message, details)


def _fail(message: str, **details: Any) -> SmokeResult:
    print(f"FAIL {message}")
    return SmokeResult(False, message, details)


def _warn(message: str) -> None:
    print(f"WARN {message}")


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_output_dir() -> Path:
    return DEFAULT_OUTPUT_ROOT / _now_slug()


def _safe_voice_payload(args: argparse.Namespace) -> dict[str, str]:
    payload: dict[str, str] = {}
    if args.voice:
        payload["voice_id"] = str(args.voice)
    if args.rate:
        payload["rate"] = str(args.rate)
    if args.volume:
        payload["volume"] = str(args.volume)
    return payload


def _deterministic_job_id(
    *,
    book_id: int,
    chapter_id: int,
    provider: str,
    voice_payload: dict[str, str],
) -> str:
    digest = hashlib.sha1(
        json.dumps(
            {
                "book_id": book_id,
                "chapter_id": chapter_id,
                "provider": provider,
                "voice": voice_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"tts-validate-b{book_id}-c{chapter_id}-{digest}"


def _read_translated_text(chapter: dict[str, Any]) -> str:
    translated_path = str(chapter.get("translated_text_path") or "").strip()
    if not translated_path:
        return ""
    path = Path(translated_path)
    if not path.exists():
        return ""
    return clean_translation_layout(path.read_text(encoding="utf-8"))


def _chapter_candidates(book_id: int, chapter_id: int | None, chapter_limit: int, db_path: Path) -> list[dict[str, Any]]:
    chapters = sorted(
        list_chapters(db_path, book_id),
        key=lambda item: int(item.get("chapter_number") or 0),
    )
    translated = [chapter for chapter in chapters if _read_translated_text(chapter).strip()]
    if chapter_id is not None:
        translated = [chapter for chapter in translated if int(chapter.get("id") or 0) == chapter_id]
    if chapter_limit > 0:
        translated = translated[:chapter_limit]
    return translated


def _build_chapter_plan(db_path: Path, book_id: int, chapter: dict[str, Any]) -> ChapterPlan:
    text = _read_translated_text(chapter)
    normalized = normalize_text(text, backend=settings.tts_normalizer)
    chunks = chunk_text(
        normalized.text,
        chapter_id=int(chapter.get("id") or 0),
        max_chars=settings.tts_chunk_max_chars,
        max_sentences=settings.tts_chunk_max_sentences,
    )
    warnings: list[str] = []
    qa_report = get_qa_report(db_path, book_id, int(chapter.get("id") or 0))
    return ChapterPlan(
        chapter_id=int(chapter.get("id") or 0),
        chapter_number=int(chapter.get("chapter_number") or 0),
        title=str(chapter.get("title") or ""),
        translated_path=str(chapter.get("translated_text_path") or ""),
        char_count=len(normalized.text),
        chunk_count=len(chunks),
        has_audio=bool(str(chapter.get("audio_path") or "").strip() and Path(str(chapter.get("audio_path"))).exists()),
        qa_status=str(qa_report.get("overall_status") or "") if qa_report else "",
        chinese_leakage_count=int(qa_report.get("chinese_leakage_count") or 0) if qa_report else 0,
        warnings=warnings,
    )


def build_real_provider_plan(
    *,
    db_path: Path,
    book_id: int,
    chapter_id: int | None,
    chapter_limit: int,
    max_chars: int | None,
) -> tuple[dict[str, Any], list[ChapterPlan]]:
    book = get_book_by_id(db_path, book_id)
    if not book:
        raise ValueError(f"Book {book_id} not found")
    candidates = _chapter_candidates(book_id, chapter_id, chapter_limit, db_path)
    if not candidates:
        raise ValueError("No translated chapters found for the selected scope")

    plans: list[ChapterPlan] = []
    total_chars = 0
    total_chunks = 0
    for chapter in candidates:
        plan = _build_chapter_plan(db_path, book_id, chapter)
        if plan.qa_status == "FAIL":
            plan.warnings.append("QA overall status is FAIL")
        if plan.chinese_leakage_count > 0:
            plan.warnings.append(f"QA detected {plan.chinese_leakage_count} Chinese leakage points")
        if plan.has_audio:
            plan.warnings.append("Chapter already has audio")
        total_chars += plan.char_count
        total_chunks += plan.chunk_count
        plans.append(plan)

    if max_chars is not None and total_chars > max_chars:
        raise ValueError(
            f"Selected scope has {total_chars} characters, exceeding --max-chars limit {max_chars}"
        )

    selection = "single chapter" if chapter_id is not None else "book selection"
    return (
        {
            "book_id": book_id,
            "book_title": str(book.get("title") or ""),
            "author": str(book.get("author") or ""),
            "selection_mode": selection,
            "chapter_count": len(plans),
            "estimated_characters": total_chars,
            "estimated_chunks": total_chunks,
        },
        plans,
    )


def _estimate_storage_bytes(total_chars: int) -> int:
    estimated_seconds = max(10, total_chars / 14)
    bytes_per_second = 16000
    return int(estimated_seconds * bytes_per_second)


@contextmanager
def _override_tts_provider(provider: str | None):
    if not provider:
        yield
        return
    original = settings.tts_provider
    settings.tts_provider = provider
    try:
        yield
    finally:
        settings.tts_provider = original


def _provider_preflight(provider: str, voice_payload: dict[str, str]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    voice = VoiceConfig.from_mapping(voice_payload)
    provider_name = provider.strip().lower()
    if provider_name in {"f5", "f5_tts", "f5_vietnamese", "vivioice", "vivoice"}:
        if not voice.reference_audio_path.strip():
            warnings.append("Reference audio is not configured for F5 Vietnamese voice cloning")
        else:
            ref_path = Path(voice.reference_audio_path).expanduser()
            if not ref_path.is_absolute():
                ref_path = PROJECT_ROOT / ref_path
            if not ref_path.exists():
                warnings.append("Configured reference audio file does not exist")
        if not voice.reference_text.strip():
            warnings.append("Reference transcript is not configured for F5 Vietnamese voice cloning")
        if settings.tts_ckpt_file and settings.tts_vocab_file:
            for label, value in (("ckpt", settings.tts_ckpt_file), ("vocab", settings.tts_vocab_file)):
                path = Path(value).expanduser()
                if not path.is_absolute():
                    path = PROJECT_ROOT / path
                if not path.exists():
                    warnings.append(f"Configured {label} path does not exist")
        elif settings.tts_model_repo.strip():
            notes.append(f"Model files will resolve from repo {settings.tts_model_repo}")
        else:
            warnings.append("No local checkpoint paths or model repo are configured for F5 Vietnamese")
    elif provider_name == "edge_tts":
        notes.append("edge-tts provider selected; local ffmpeg is still required for merge validation")
    else:
        warnings.append(f"Unsupported or unverified provider override: {provider}")
    return warnings, notes


def _preflight_summary(
    *,
    output_dir: Path,
    data_dir: Path,
    provider: str,
    voice_payload: dict[str, str],
    plan: dict[str, Any],
    chapter_plans: list[ChapterPlan],
) -> dict[str, Any]:
    provider_warnings, provider_notes = _provider_preflight(provider, voice_payload)
    warnings = list(provider_warnings)
    warnings.extend(provider_notes)

    ffmpeg_ok = True
    ffmpeg_error = ""
    try:
        ensure_ffmpeg()
    except Exception as exc:  # pragma: no cover - exercised in runtime smoke
        ffmpeg_ok = False
        ffmpeg_error = redact_validation_text(exc)
        warnings.append(ffmpeg_error)

    output_dir.mkdir(parents=True, exist_ok=True)
    writable = output_dir.is_dir()
    if not writable:
        warnings.append("Output directory could not be created")

    selected_warnings: list[str] = []
    for chapter in chapter_plans:
        selected_warnings.extend(
            f"Ch {chapter.chapter_number}: {warning}"
            for warning in chapter.warnings
        )

    return {
        "provider": provider,
        "voice": {
            "voice_id": voice_payload.get("voice_id") or "default",
            "rate": voice_payload.get("rate") or "-5%",
            "volume": voice_payload.get("volume") or "+0%",
        },
        "ffmpeg_available": ffmpeg_ok,
        "ffmpeg_error": ffmpeg_error,
        "ffprobe_available": ffprobe_available(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "estimated_storage_bytes": _estimate_storage_bytes(int(plan["estimated_characters"])),
        "warnings": warnings + selected_warnings,
    }


def _report_contains_secret(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "api_key=secret",
            "api_key=sk-",
            "authorization: bearer sk-",
            "authorization: bearer eyj",
            "secret=sk-",
            "password=123",
        )
    )


def _write_listening_checklist(output_dir: Path) -> Path:
    checklist = output_dir / "listening-checklist.md"
    checklist.write_text(
        "\n".join(
            [
                "# Listening Spot-Check Checklist",
                "",
                "- Beginning of chapter: NOT_TESTED",
                "- Middle of chapter: NOT_TESTED",
                "- End of chapter: NOT_TESTED",
                "- Dialogue transitions: NOT_TESTED",
                "- Proper names: NOT_TESTED",
                "- Numbers: NOT_TESTED",
                "- Punctuation pauses: NOT_TESTED",
                "- Chunk boundaries: NOT_TESTED",
                "- Chapter boundaries: NOT_TESTED",
                "- Volume consistency: NOT_TESTED",
                "- Duplicated or missing speech: NOT_TESTED",
                "- Silence / clipping: NOT_TESTED",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return checklist


_REPORT_PATH_KEYS = {
    "data_dir",
    "output_dir",
    "path",
    "report_json_path",
    "translated_path",
    "wav_path",
    "mp3_path",
    "output_mp3_path",
    "output_m4b_path",
}


def _sanitize_validation_report_value(value: Any, *, key: str = "") -> Any:
    if key.lower() in _REPORT_PATH_KEYS:
        return ""
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_validation_report_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_validation_report_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_validation_report_value(item) for item in value]
    if isinstance(value, str):
        return redact_validation_text(value, max_len=500)
    return value


def _write_validation_report(
    *,
    output_dir: Path,
    mode: str,
    plan: dict[str, Any],
    preflight: dict[str, Any],
    chapter_plans: list[ChapterPlan],
    results: list[SmokeResult],
    mp3_reports: list[dict[str, Any]],
    m4b_report: dict[str, Any] | None,
    route_results: list[SmokeResult],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "preflight": preflight,
        "chapters": [asdict(plan_item) for plan_item in chapter_plans],
        "results": [asdict(item) for item in results],
        "mp3_reports": mp3_reports,
        "m4b_report": m4b_report,
        "route_results": [asdict(item) for item in route_results],
    }
    sanitized_payload = _sanitize_validation_report_value(payload)
    json_path = output_dir / "tts-operational-report.json"
    json_text = json.dumps(sanitized_payload, ensure_ascii=False, indent=2)
    if _report_contains_secret(json_text):
        raise RuntimeError("Validation JSON report sanitization failed")
    json_path.write_text(json_text, encoding="utf-8")

    lines = [
        "# TTS Operational Report",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Mode: {mode}",
        f"- Book: {plan['book_title']} (#{plan['book_id']})",
        f"- Chapters: {plan['chapter_count']}",
        f"- Estimated characters: {plan['estimated_characters']}",
        f"- Estimated chunks: {plan['estimated_chunks']}",
        f"- Provider: {preflight['provider']}",
        f"- Voice: {preflight['voice']['voice_id']}",
        "",
        "## Preflight",
        "",
        f"- ffmpeg available: {'yes' if preflight['ffmpeg_available'] else 'no'}",
        f"- ffprobe available: {'yes' if preflight['ffprobe_available'] else 'no'}",
        f"- Estimated storage: {preflight['estimated_storage_bytes']} bytes",
        "",
    ]
    if preflight["warnings"]:
        lines.extend(["### Warnings", ""])
        lines.extend(f"- {redact_validation_text(item, max_len=300)}" for item in preflight["warnings"])
        lines.append("")

    lines.extend(["## Chapter Scope", ""])
    for chapter in chapter_plans:
        lines.append(
            f"- Ch {chapter.chapter_number} #{chapter.chapter_id}: {chapter.title} | {chapter.char_count} chars | {chapter.chunk_count} chunks | QA={chapter.qa_status or 'NOT_RUN'}"
        )
    lines.append("")

    lines.extend(["## Results", ""])
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        lines.append(f"- {status}: {redact_validation_text(result.message, max_len=300)}")
    lines.append("")

    if mp3_reports:
        lines.extend(["## MP3 Inspection", ""])
        for report in mp3_reports:
            lines.append(
                f"- {report.get('path')}: size={report.get('size_bytes', 0)} duration={report.get('duration_seconds', 0)} warnings={len(report.get('warnings') or [])}"
            )
        lines.append("")

    if m4b_report:
        lines.extend(
            [
                "## M4B Inspection",
                "",
                f"- Exists: {'yes' if m4b_report.get('exists') else 'no'}",
                f"- Size: {m4b_report.get('size_bytes', 0)} bytes",
                f"- Duration: {m4b_report.get('duration_seconds', 0)}",
                f"- Chapter markers: {m4b_report.get('chapter_count', 0)}",
                "",
            ]
        )

    if route_results:
        lines.extend(["## Protected Route Checks", ""])
        for result in route_results:
            lines.append(f"- {'PASS' if result.ok else 'FAIL'}: {redact_validation_text(result.message, max_len=300)}")
        lines.append("")

    report_path = output_dir / "tts-operational-report.md"
    report_text = "\n".join(lines)
    if _report_contains_secret(report_text):
        raise RuntimeError("Validation report sanitization failed")
    report_path.write_text(report_text, encoding="utf-8")
    _write_listening_checklist(output_dir)
    return report_path


def update_validation_report_routes(report_path: Path, route_results: list[SmokeResult]) -> None:
    """Add protected-route evidence after the optional live smoke completes."""
    json_path = report_path.with_name("tts-operational-report.json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["route_results"] = _sanitize_validation_report_value([asdict(item) for item in route_results])
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if _report_contains_secret(json_text):
        raise RuntimeError("Validation JSON report sanitization failed")
    json_path.write_text(json_text, encoding="utf-8")

    report_text = report_path.read_text(encoding="utf-8")
    report_text = report_text.split("\n## Protected Route Checks", 1)[0].rstrip() + "\n"
    report_lines = ["## Protected Route Checks", ""]
    report_lines.extend(
        f"- {'PASS' if result.ok else 'FAIL'}: {redact_validation_text(result.message, max_len=300)}"
        for result in route_results
    )
    report_text += "\n".join(report_lines) + "\n"
    if _report_contains_secret(report_text):
        raise RuntimeError("Validation report sanitization failed")
    report_path.write_text(report_text, encoding="utf-8")


def run_fixture_smoke() -> list[SmokeResult]:
    results: list[SmokeResult] = []
    with tempfile.TemporaryDirectory(prefix="novel-tnn-tts-smoke-") as tmp:
        root = Path(tmp)
        db_path = root / "pipeline.db"
        data_dir = root / "data"
        init_db(db_path)
        book_id = add_book(db_path, "Smoke TTS Book", author="Novel-TNN")

        chapter_specs = [
            (
                1,
                "Khởi đầu",
                "Chương một. Đây là đoạn tiếng Việt đầu tiên. Nhân vật tiến vào sơn cốc. Gió nổi lên rất khẽ.",
            ),
            (
                2,
                "Tiếp tục",
                "Chương hai. Hắn dừng lại trước cửa động phủ. Một hồi chuông rất xa vọng tới rồi im bặt.",
            ),
        ]

        chapter_ids: list[int] = []
        translated_dir = data_dir / "translated"
        translated_dir.mkdir(parents=True, exist_ok=True)
        for chapter_number, title, text in chapter_specs:
            chapter_id = add_chapter(db_path, book_id, chapter_number, title)
            chapter_ids.append(chapter_id)
            translation_path = translated_dir / f"chapter-{chapter_number}.txt"
            translation_path.write_text(text, encoding="utf-8")
            update_chapter_paths(db_path, chapter_id, translated_text_path=translation_path, status="translated")

        pipeline = TTSPipeline(db_path, data_dir, engine_factory=lambda: FixtureEngine())
        reports = []
        for chapter_id in chapter_ids:
            report = pipeline.generate_chapter(book_id=book_id, chapter_id=chapter_id, job_id=f"smoke-tts-{chapter_id}")
            reports.append(report)
            if report.status != "completed":
                results.append(_fail(f"chapter {chapter_id} TTS status={report.status} error={report.error_message}"))
                continue
            output_path = Path(report.output_mp3_path)
            if not output_path.exists() or output_path.stat().st_size <= 0:
                results.append(_fail(f"chapter {chapter_id} MP3 missing or empty"))
                continue
            status = pipeline.get_job_status(report.job_id)
            if not status or not status.get("audio_summary", {}).get("output_mp3_ready"):
                results.append(_fail(f"chapter {chapter_id} audio summary did not report ready MP3"))
                continue
            results.append(_pass(f"chapter {chapter_id} generated MP3 ({output_path.stat().st_size} bytes)"))

        if all(report.status == "completed" for report in reports):
            try:
                output_m4b = pipeline.generate_book_m4b(book_id, job_id="smoke-book")
            except Exception as exc:  # pragma: no cover - exercised in smoke runs
                results.append(_fail(f"M4B generation failed: {exc}"))
            else:
                if not output_m4b.exists() or output_m4b.stat().st_size <= 0:
                    results.append(_fail("M4B artifact missing or empty"))
                else:
                    results.append(_pass(f"M4B artifact ready ({output_m4b.stat().st_size} bytes)"))
    return results


def run_real_provider_smoke(
    *,
    db_path: Path,
    data_dir: Path,
    book_id: int,
    chapter_id: int | None,
    chapter_limit: int,
    max_chars: int | None,
    provider: str | None,
    voice_payload: dict[str, str],
    output_dir: Path,
    generate_m4b: bool,
    dry_run: bool,
    resume: bool,
    overwrite: bool,
    yes: bool,
) -> tuple[list[SmokeResult], list[dict[str, Any]], dict[str, Any] | None, Path]:
    init_db(db_path)
    active_provider = str(provider or settings.tts_provider)
    plan, chapter_plans = build_real_provider_plan(
        db_path=db_path,
        book_id=book_id,
        chapter_id=chapter_id,
        chapter_limit=chapter_limit,
        max_chars=max_chars,
    )
    preflight = _preflight_summary(
        output_dir=output_dir,
        data_dir=data_dir,
        provider=active_provider,
        voice_payload=voice_payload,
        plan=plan,
        chapter_plans=chapter_plans,
    )
    results: list[SmokeResult] = []
    route_results: list[SmokeResult] = []
    mp3_reports: list[dict[str, Any]] = []
    m4b_report: dict[str, Any] | None = None

    _write_validation_report(
        output_dir=output_dir,
        mode="dry-run" if dry_run else "real-provider",
        plan=plan,
        preflight=preflight,
        chapter_plans=chapter_plans,
        results=results,
        mp3_reports=mp3_reports,
        m4b_report=m4b_report,
        route_results=route_results,
    )

    print(
        f"PLAN provider={active_provider} book={plan['book_title']} chapters={plan['chapter_count']} "
        f"chars={plan['estimated_characters']} chunks={plan['estimated_chunks']}"
    )
    if preflight["warnings"]:
        for item in preflight["warnings"]:
            _warn(redact_validation_text(item, max_len=300))

    if dry_run:
        results.append(_pass("Dry-run completed without provider invocation", chapter_count=plan["chapter_count"]))
        report_path = _write_validation_report(
            output_dir=output_dir,
            mode="dry-run",
            plan=plan,
            preflight=preflight,
            chapter_plans=chapter_plans,
            results=results,
            mp3_reports=mp3_reports,
            m4b_report=m4b_report,
            route_results=route_results,
        )
        return results, mp3_reports, m4b_report, report_path

    if not yes:
        print("Type YES to continue real-provider synthesis:", end=" ", flush=True)
        if input().strip() != "YES":
            raise RuntimeError("Real-provider validation aborted by operator")

    pipeline = TTSPipeline(db_path, data_dir)
    book = get_book_by_id(db_path, book_id) or {}
    with _override_tts_provider(provider):
        for chapter_plan in chapter_plans:
            chapter = get_chapter_by_id(db_path, chapter_plan.chapter_id)
            if not chapter:
                results.append(_fail(f"chapter {chapter_plan.chapter_id} not found during execution"))
                continue
            if chapter_plan.has_audio and not overwrite:
                results.append(
                    _fail(
                        f"chapter {chapter_plan.chapter_number} already has audio; rerun with --overwrite to regenerate"
                    )
                )
                continue
            job_id = _deterministic_job_id(
                book_id=book_id,
                chapter_id=chapter_plan.chapter_id,
                provider=active_provider,
                voice_payload=voice_payload,
            )
            report = pipeline.generate_chapter(
                book_id=book_id,
                chapter_id=chapter_plan.chapter_id,
                job_id=job_id,
                voice_config=voice_payload,
                resume=resume or not overwrite,
            )
            if report.status != "completed":
                results.append(_fail(f"chapter {chapter_plan.chapter_number} failed: {report.error_message or report.status}"))
                continue
            output_path = Path(report.output_mp3_path)
            inspection = inspect_media_artifact(output_path, include_chapters=False)
            mp3_reports.append(inspection)
            if not inspection.get("exists") or int(inspection.get("size_bytes") or 0) <= 0:
                results.append(_fail(f"chapter {chapter_plan.chapter_number} MP3 missing or empty"))
            else:
                results.append(
                    _pass(
                        f"chapter {chapter_plan.chapter_number} MP3 ready ({inspection['size_bytes']} bytes)",
                        job_id=job_id,
                        output=output_path.name,
                    )
                )

        if generate_m4b and mp3_reports:
            selected_paths = [
                Path(get_chapter_by_id(db_path, plan_item.chapter_id).get("audio_path") or "")
                for plan_item in chapter_plans
                if get_chapter_by_id(db_path, plan_item.chapter_id)
                and str(get_chapter_by_id(db_path, plan_item.chapter_id).get("audio_path") or "").strip()
            ]
            selected_paths = [path for path in selected_paths if path.exists()]
            if selected_paths:
                m4b_path = output_dir / f"book{book_id}-validation.m4b"
                if m4b_path.exists() and not overwrite:
                    raise RuntimeError(f"M4B validation artifact already exists at {m4b_path.name}; rerun with --overwrite")
                merge_book_m4b(
                    selected_paths,
                    m4b_path,
                    metadata=AudioMetadata(
                        title=str(book.get("title") or f"Book {book_id}"),
                        author=str(book.get("author") or ""),
                        source_book=str(book.get("title") or f"Book {book_id}"),
                    ),
                )
                m4b_report = inspect_media_artifact(m4b_path, include_chapters=True)
                if not m4b_report.get("exists") or int(m4b_report.get("size_bytes") or 0) <= 0:
                    results.append(_fail("validation M4B artifact missing or empty"))
                else:
                    results.append(
                        _pass(
                            f"validation M4B ready ({m4b_report['size_bytes']} bytes)",
                            path=m4b_path.name,
                            chapter_markers=m4b_report.get("chapter_count", 0),
                        )
                    )

    report_path = _write_validation_report(
        output_dir=output_dir,
        mode="real-provider",
        plan=plan,
        preflight=preflight,
        chapter_plans=chapter_plans,
        results=results,
        mp3_reports=mp3_reports,
        m4b_report=m4b_report,
        route_results=route_results,
    )
    return results, mp3_reports, m4b_report, report_path


def run_server_route_smoke(
    *,
    base_url: str,
    username: str,
    password: str,
    book_id: int,
    chapter_id: int,
    check_m4b_route: bool,
) -> list[SmokeResult]:
    results: list[SmokeResult] = []
    safe_base_url = _validate_live_base_url(base_url)

    def stream_status(client: httpx.Client, url: str, *, headers: dict[str, str] | None = None) -> int:
        with client.stream("GET", url, headers=headers) as response:
            # Read only a bounded prefix so a long audiobook is never buffered in memory.
            if response.status_code == 200:
                next(response.iter_bytes(chunk_size=1024), b"")
            return response.status_code

    with httpx.Client(base_url=safe_base_url, timeout=30.0, follow_redirects=False) as client:
        unauthenticated_status = stream_status(client, f"/api/books/{book_id}/chapters/{chapter_id}/audio")
        if unauthenticated_status not in {401, 403}:
            results.append(_fail(f"unauthenticated audio route returned {unauthenticated_status}, expected 401/403"))
            return results
        login = client.post("/api/auth/login", json={"username": username, "password": password})
        if login.status_code != 200:
            results.append(_fail(f"login failed with status {login.status_code}"))
            return results
        token = login.json().get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"}
        stream_status_code = stream_status(client, f"/api/books/{book_id}/chapters/{chapter_id}/audio", headers=headers)
        if stream_status_code != 200:
            results.append(_fail(f"authenticated audio stream returned {stream_status_code}"))
        else:
            results.append(_pass("authenticated audio stream returned 200"))
        ranged_status = stream_status(
            client,
            f"/api/books/{book_id}/chapters/{chapter_id}/audio",
            headers={**headers, "Range": "bytes=0-15"},
        )
        if ranged_status not in {200, 206}:
            results.append(_fail(f"audio range request returned {ranged_status}"))
        else:
            results.append(_pass(f"audio range request returned {ranged_status}"))
        download_status = stream_status(client, f"/api/books/{book_id}/chapters/{chapter_id}/audio/download", headers=headers)
        if download_status != 200:
            results.append(_fail(f"authenticated audio download returned {download_status}"))
        else:
            results.append(_pass("authenticated audio download returned 200"))
        if check_m4b_route:
            unauthenticated_m4b_status = stream_status(client, f"/api/books/{book_id}/exports/audiobook/m4b/download")
            if unauthenticated_m4b_status not in {401, 403}:
                results.append(_fail(f"unauthenticated M4B route returned {unauthenticated_m4b_status}, expected 401/403"))
            else:
                results.append(_pass("unauthenticated M4B route denied"))
            authenticated_m4b_status = stream_status(client, f"/api/books/{book_id}/exports/audiobook/m4b/download", headers=headers)
            if authenticated_m4b_status != 200:
                results.append(_fail(f"authenticated M4B download returned {authenticated_m4b_status}"))
            else:
                results.append(_pass("authenticated M4B download returned 200"))
    return results


def _validate_live_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute http(s) URL")
    hostname = (parsed.hostname or "").lower()
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and hostname not in local_hosts:
        raise ValueError("--base-url must use HTTPS outside local development")
    return base_url.rstrip("/")


def _read_smoke_password(password_file: Path) -> str:
    if not password_file.is_file() or password_file.is_symlink():
        raise ValueError("--password-file must be a regular file")
    if os.name == "posix" and stat.S_IMODE(password_file.stat().st_mode) & 0o077:
        raise ValueError("--password-file permissions must not allow group or other access")
    password = password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("--password-file is empty")
    return password


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test the Novel-TNN TTS/audio pipeline.")
    parser.add_argument("--real-provider", action="store_true", help="Use the configured real TTS provider instead of fixture audio.")
    parser.add_argument("--db-path", type=Path, help="Database path for --real-provider mode.")
    parser.add_argument("--data-dir", type=Path, help="Data directory for --real-provider mode.")
    parser.add_argument("--book-id", type=int, help="Book id for --real-provider or --base-url route checks.")
    parser.add_argument("--chapter-id", type=int, help="Specific chapter id for real-provider mode or route checks.")
    parser.add_argument("--chapter-limit", type=int, default=1, help="Maximum number of chapters to process in real-provider mode.")
    parser.add_argument("--provider", help="Optional provider override for real-provider mode.")
    parser.add_argument("--voice", help="Optional voice or voice_id override.")
    parser.add_argument("--rate", default="-5%", help="Optional speaking rate override.")
    parser.add_argument("--volume", default="+0%", help="Optional speaking volume override.")
    parser.add_argument("--max-cost", type=float, help="Optional cost ceiling for documentation/preflight only.")
    parser.add_argument("--max-chars", type=int, help="Optional hard ceiling for total characters in the selected scope.")
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir(), help="Directory for validation reports and representative artifacts.")
    parser.add_argument("--resume", action="store_true", help="Reuse deterministic job ids and completed chunks where possible.")
    parser.add_argument("--dry-run", action="store_true", help="Run preflight and reporting only without invoking the provider.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing chapter audio and validation artifacts.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt for real-provider execution.")
    parser.add_argument("--generate-m4b", action="store_true", help="Also validate representative M4B generation.")
    parser.add_argument("--base-url", help="Optional running server base URL for protected route checks.")
    parser.add_argument("--username", help="Username for protected route checks.")
    parser.add_argument("--password-file", type=Path, help="0600 file containing the password for protected route checks.")
    parser.add_argument("--check-m4b-route", action="store_true", help="Also validate protected M4B download route when --base-url is provided.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    results: list[SmokeResult] = []
    route_results: list[SmokeResult] = []
    report_path: Path | None = None

    if args.real_provider:
        if not args.db_path or not args.data_dir or not args.book_id:
            print("FAIL --real-provider requires --db-path, --data-dir, and --book-id")
            return 1
        if args.chapter_limit <= 0:
            print("FAIL --chapter-limit must be greater than zero")
            return 1
        if not args.dry_run and not args.chapter_id and args.chapter_limit > 20:
            print("FAIL real-provider mode refuses to process more than 20 chapters at once without a narrower scope")
            return 1
        if args.max_cost is not None:
            print(f"INFO Max cost guard requested: {args.max_cost:.4f} (documentation/preflight only)")
        try:
            results, _, _, report_path = run_real_provider_smoke(
                db_path=args.db_path,
                data_dir=args.data_dir,
                book_id=args.book_id,
                chapter_id=args.chapter_id,
                chapter_limit=args.chapter_limit,
                max_chars=args.max_chars,
                provider=args.provider,
                voice_payload=_safe_voice_payload(args),
                output_dir=args.output_dir,
                generate_m4b=args.generate_m4b,
                dry_run=args.dry_run,
                resume=args.resume,
                overwrite=args.overwrite,
                yes=args.yes,
            )
            print(f"INFO validation report written to {report_path}")
        except Exception as exc:
            print(f"FAIL {redact_validation_text(exc)}")
            return 1
    else:
        results.extend(run_fixture_smoke())

    if args.base_url:
        if not args.username or not args.password_file or not args.book_id or not args.chapter_id:
            print("FAIL --base-url route checks require --username, --password-file, --book-id, and --chapter-id")
            return 1
        try:
            route_results = run_server_route_smoke(
                base_url=args.base_url,
                username=args.username,
                password=_read_smoke_password(args.password_file),
                book_id=args.book_id,
                chapter_id=args.chapter_id,
                check_m4b_route=args.check_m4b_route,
            )
        except ValueError as exc:
            print(f"FAIL {redact_validation_text(exc)}")
            return 1
        results.extend(route_results)
        if report_path is not None:
            update_validation_report_routes(report_path, route_results)

    failed = [result for result in results if not result.ok]
    print(f"SUMMARY {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
