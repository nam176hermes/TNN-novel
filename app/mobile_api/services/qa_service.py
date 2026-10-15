from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from app.translation.qa_report import merge_qa_report
from app.database.db import (
    get_chapter_by_id,
    get_qa_report as db_get_qa_report,
    list_glossary,
    list_qa_reports,
    save_qa_report,
)


class ChapterContentReader(Protocol):
    db_path: Path

    def get_chapter_source(self, chapter_id: int) -> str | None: ...

    def get_chapter_translation(self, chapter_id: int) -> str | None: ...


CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n+", text or "") if part.strip()]


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 2)


def _repeated_paragraph_warning(translated_text: str) -> bool:
    paragraphs = _paragraphs(translated_text)
    seen: set[str] = set()
    for paragraph in paragraphs:
        normalized = re.sub(r"\s+", " ", paragraph).strip().lower()
        if len(normalized) < 12:
            continue
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def _report_status(report: dict, chapter: dict) -> str:
    revision = report.get("content_revision")
    if revision is None:
        return "legacy_unverified"
    if revision != chapter.get("content_revision") or report.get("overall_status") == "STALE":
        return "stale"
    payload = report.get("report_json") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return "legacy_unverified"
    if not isinstance(payload, dict) or payload.get("report_version") != 1:
        return "legacy_unverified"
    provenance = payload.get("provenance") or {}
    if provenance.get("translation_hash") != chapter.get("translation_hash"):
        return "stale"
    if str(report.get("verdict", "")).upper() == "FAIL":
        return "fail"
    return "pass" if payload.get("quality_status") == "pass" else payload.get("quality_status", "partial")


def _locked_glossary_violations(glossary_terms: list[dict], source_text: str, translated_text: str) -> list[dict]:
    violations: list[dict] = []
    for term in glossary_terms:
        if int(term.get("locked") or 0) != 1 or int(term.get("approved") or 0) != 1:
            continue
        source = str(term.get("source_term") or "").strip()
        target = str(term.get("target_term") or "").strip()
        if not source or not target or source not in source_text:
            continue
        if target not in translated_text:
            violations.append(
                {
                    "source_term": source,
                    "expected": target,
                    "type": term.get("term_type") or term.get("category") or "term",
                    "message": f"Thuật ngữ khóa {source} phải dùng '{target}'.",
                }
            )
    return violations


def build_deterministic_chapter_qa_report(
    *,
    book_id: int,
    chapter_id: int,
    source_text: str,
    translated_text: str,
    glossary_terms: list[dict],
    job_id: str = "",
) -> dict:
    chinese_leakage_count = len(CJK_PATTERN.findall(translated_text or ""))
    length_ratio = _safe_ratio(len(translated_text or ""), len(source_text or ""))
    source_paragraphs = _paragraphs(source_text)
    translated_paragraphs = _paragraphs(translated_text)
    missing_paragraph_warning = bool(
        len(source_paragraphs) >= 2
        and len(translated_paragraphs) < max(1, int(len(source_paragraphs) * 0.55))
    )
    repetition_warning = _repeated_paragraph_warning(translated_text)
    glossary_violations = _locked_glossary_violations(glossary_terms, source_text, translated_text)
    style_warnings: list[dict] = []
    if "。" in translated_text or "，" in translated_text:
        style_warnings.append({"type": "chinese_punctuation", "message": "Bản dịch còn dấu câu tiếng Trung."})
    if length_ratio and (length_ratio < 0.45 or length_ratio > 8.0):
        style_warnings.append(
            {
                "type": "length_ratio",
                "message": "Độ dài bản dịch lệch bất thường so với bản gốc.",
                "length_ratio": length_ratio,
            }
        )

    issues: list[dict] = []
    if chinese_leakage_count:
        issues.append(
            {
                "type": "chinese_leakage",
                "severity": "high",
                "message": f"Còn {chinese_leakage_count} ký tự Hán trong bản dịch.",
            }
        )
    if missing_paragraph_warning:
        issues.append(
            {
                "type": "missing_paragraph",
                "severity": "medium",
                "message": "Số đoạn dịch ít hơn đáng kể so với bản gốc.",
            }
        )
    if repetition_warning:
        issues.append(
            {
                "type": "repetition",
                "severity": "high",
                "message": "Phát hiện đoạn dịch bị lặp.",
            }
        )
    for violation in glossary_violations:
        issues.append({"type": "glossary_violation", "severity": "high", **violation})
    for warning in style_warnings:
        issues.append({"severity": "medium", **warning})

    term_consistency_status = "FAIL" if glossary_violations else "PASS"
    name_consistency_status = "FAIL" if any(
        str(item.get("type") or "").lower() in {"character", "title"} for item in glossary_violations
    ) else "PASS"
    if chinese_leakage_count or repetition_warning or glossary_violations:
        overall_status = "FAIL"
    elif missing_paragraph_warning or style_warnings:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"
    quality_score = {"PASS": 9.0, "WARNING": 6.5, "FAIL": 3.0}[overall_status]

    suggested_fixes = [
        {
            "type": "replace_term",
            "source_term": item["source_term"],
            "suggested_fix": item["expected"],
            "message": item["message"],
        }
        for item in glossary_violations
    ]
    return {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "job_id": job_id,
        "overall_status": overall_status,
        "verdict": overall_status,
        "quality_score": quality_score,
        "fidelity_score": quality_score,
        "style_score": 6 if style_warnings or repetition_warning else 9,
        "glossary_score": 4 if glossary_violations else 9,
        "audiobook_score": 0,
        "missing_paragraph_warning": missing_paragraph_warning,
        "chinese_leakage_count": chinese_leakage_count,
        "name_consistency_status": name_consistency_status,
        "term_consistency_status": term_consistency_status,
        "length_ratio": length_ratio,
        "repetition_warning": repetition_warning,
        "style_warnings": style_warnings,
        "glossary_violations": glossary_violations,
        "suggested_fixes": suggested_fixes,
        "issues": issues,
    }


class QAService:
    def __init__(self, pipeline_service: ChapterContentReader):
        self.pipeline = pipeline_service

    def get_qa_report(self, book_id: int, chapter_id: int) -> dict | None:
        """Get QA report for a chapter, reading from database."""
        report = db_get_qa_report(self.pipeline.db_path, book_id, chapter_id)
        if report:
            # Parse report_json if it's a string
            for json_field in ("report_json", "style_warnings", "glossary_violations", "suggested_fixes"):
                if isinstance(report.get(json_field), str):
                    try:
                        report[json_field] = json.loads(report[json_field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            if isinstance(report.get("report_json"), str):
                try:
                    report["report_json"] = json.loads(report["report_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            chapter = get_chapter_by_id(self.pipeline.db_path, chapter_id)
            if not chapter or chapter["book_id"] != book_id:
                return None
            status = _report_status(report, chapter)
            report["quality_status"] = status
            if status in {"stale", "legacy_unverified"}:
                report["previous_verdict"] = report["verdict"]
                report["verdict"] = "STALE" if status == "stale" else "NOT_RUN"
                report["overall_status"] = report["verdict"]
            return report
        return None

    def run_deterministic_qa(self, book_id: int, chapter_id: int, job_id: str = "", *,
                             connection=None, chapter=None, source_text=None,
                             translated_text=None, glossary_terms=None) -> dict:
        """Run deterministic chapter QA without calling an LLM provider."""
        snapshot = chapter if chapter is not None else get_chapter_by_id(self.pipeline.db_path, chapter_id)
        source_text = source_text if source_text is not None else self.pipeline.get_chapter_source(chapter_id) or ""
        translated_text = translated_text if translated_text is not None else self.pipeline.get_chapter_translation(chapter_id) or ""
        if not translated_text:
            raise ValueError(f"No translation for chapter {chapter_id}")
        glossary_terms = glossary_terms if glossary_terms is not None else list_glossary(self.pipeline.db_path, book_id)
        report = build_deterministic_chapter_qa_report(
            book_id=book_id,
            chapter_id=chapter_id,
            source_text=source_text,
            translated_text=translated_text,
            glossary_terms=glossary_terms,
            job_id=job_id,
        )
        save_qa_report(
            self.pipeline.db_path,
            connection=connection,
            book_id=book_id,
            content_revision=snapshot["content_revision"] if snapshot else None,
            component="rule_based",
            chapter_id=chapter_id,
            quality_score=report["quality_score"],
            fidelity_score=report["fidelity_score"],
            style_score=report["style_score"],
            glossary_score=report["glossary_score"],
            audiobook_score=report["audiobook_score"],
            verdict=report["verdict"],
            job_id=job_id,
            overall_status=report["overall_status"],
            missing_paragraph_warning=report["missing_paragraph_warning"],
            chinese_leakage_count=report["chinese_leakage_count"],
            name_consistency_status=report["name_consistency_status"],
            term_consistency_status=report["term_consistency_status"],
            length_ratio=report["length_ratio"],
            repetition_warning=report["repetition_warning"],
            style_warnings=report["style_warnings"],
            glossary_violations=report["glossary_violations"],
            suggested_fixes=report["suggested_fixes"],
            report_json=json.dumps(report, ensure_ascii=False),
        )
        return report

    def run_qa_check(
        self,
        book_id: int,
        chapter_id: int,
        model: str | None = None,
        host: str | None = None,
        *, api_key: str | None = None, provider_id: str | None = None, job_id: str = "",
    ) -> dict:
        """Run QA check and return formatted report."""
        snapshot = get_chapter_by_id(self.pipeline.db_path, chapter_id)
        options = {key: value for key, value in {"api_key": api_key, "provider_id": provider_id, "job_id": job_id}.items() if value}
        report = self.pipeline.run_qa_check(book_id, chapter_id, model, host, **options)
        source_text = self.pipeline.get_chapter_source(chapter_id) or ""
        translated_text = self.pipeline.get_chapter_translation(chapter_id) or ""
        deterministic = build_deterministic_chapter_qa_report(
                book_id=book_id,
                chapter_id=chapter_id,
                source_text=source_text,
                translated_text=translated_text,
                glossary_terms=list_glossary(self.pipeline.db_path, book_id),
        )
        report = merge_qa_report(deterministic, report, {"complete": report.get("qa_complete", True), "required": True})
        report["chinese_leakage_count"] = deterministic["chinese_leakage_count"]
        report["glossary_violations"] = deterministic["glossary_violations"]
        result = {
            "chapter_id": chapter_id,
            "book_id": book_id,
            "quality_score": report.get("quality_score", 0),
            "fidelity_score": report.get("fidelity_score", 0),
            "style_score": report.get("style_score", 0),
            "glossary_score": report.get("glossary_score", 0),
            "audiobook_score": report.get("audiobook_score", 0),
            "verdict": report.get("verdict", "UNKNOWN"),
            "issues": report.get("issues", []),
            "overall_status": report.get("overall_status", report.get("verdict", "UNKNOWN")),
            "chinese_leakage_count": report.get("chinese_leakage_count", 0),
            "glossary_violations": report.get("glossary_violations", []),
            "raw_report": report,
            "created_at": "",
        }
        # Persist the report to database
        save_qa_report(
                self.pipeline.db_path,
                book_id=book_id,
                content_revision=snapshot["content_revision"] if snapshot else None,
                expected_translation_hash=snapshot.get("translation_hash") if snapshot else None,
                job_id=job_id,
                chapter_id=chapter_id,
                quality_score=result["quality_score"],
                fidelity_score=result["fidelity_score"],
                style_score=result["style_score"],
                glossary_score=result["glossary_score"],
                audiobook_score=result["audiobook_score"],
                verdict=result["verdict"],
                overall_status=result["overall_status"],
                chinese_leakage_count=result["chinese_leakage_count"],
                term_consistency_status=(
                    deterministic.get("term_consistency_status", "NOT_RUN") if deterministic else "NOT_RUN"
                ),
                glossary_violations=result["glossary_violations"],
                report_json=json.dumps(report),
        )
        return result

    def get_book_qa_summary(self, book_id: int) -> dict:
        """Get QA summary for a book."""
        chapters = self.pipeline.list_chapters(book_id)
        total = len(chapters)
        qa_done = 0
        total_score = 0.0
        pass_count = 0
        fail_count = 0
        chapter_details = []

        # Load all saved QA reports for this book
        saved_reports = list_qa_reports(self.pipeline.db_path, book_id)
        reports_by_chapter = {r["chapter_id"]: r for r in saved_reports}

        for chapter in chapters:
            ch_id = chapter["id"]
            report = reports_by_chapter.get(ch_id)
            if report:
                score = report.get("quality_score", 0)
                verdict = str(report.get("verdict", "UNKNOWN") or "UNKNOWN")
                status = _report_status(report, chapter)
                if status not in {"stale", "legacy_unverified"}:
                    qa_done += 1
                    total_score += score
                if status == "pass":
                    pass_count += 1
                elif status == "fail":
                    fail_count += 1
                chapter_details.append({
                    "chapter_id": ch_id,
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "qa_score": score,
                    "verdict": verdict,
                    "status": status,
                })
            else:
                chapter_details.append({
                    "chapter_id": ch_id,
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "qa_score": 0,
                    "verdict": "UNKNOWN",
                    "status": "translated" if chapter.get("translated_text_path") else "pending",
                })

        avg_score = total_score / qa_done if qa_done > 0 else 0

        return {
            "book_id": book_id,
            "total_chapters": total,
            "qa_done": qa_done,
            "avg_quality_score": round(avg_score, 1),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "chapters": chapter_details,
        }
