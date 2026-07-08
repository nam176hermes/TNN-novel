from __future__ import annotations

import json

from app.database.db import get_qa_report as db_get_qa_report, list_qa_reports, save_qa_report
from app.mobile_api.services.pipeline_service import PipelineService


class QAService:
    def __init__(self, pipeline_service: PipelineService):
        self.pipeline = pipeline_service

    def get_qa_report(self, book_id: int, chapter_id: int) -> dict | None:
        """Get QA report for a chapter, reading from database."""
        report = db_get_qa_report(self.pipeline.db_path, book_id, chapter_id)
        if report:
            # Parse report_json if it's a string
            if isinstance(report.get("report_json"), str):
                try:
                    report["report_json"] = json.loads(report["report_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return report
        return None

    def run_qa_check(
        self,
        book_id: int,
        chapter_id: int,
        model: str | None = None,
        host: str | None = None,
    ) -> dict:
        """Run QA check and return formatted report."""
        report = self.pipeline.run_qa_check(book_id, chapter_id, model, host)
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
            "raw_report": report,
            "created_at": "",
        }
        # Persist the report to database
        try:
            save_qa_report(
                self.pipeline.db_path,
                book_id=book_id,
                chapter_id=chapter_id,
                quality_score=result["quality_score"],
                fidelity_score=result["fidelity_score"],
                style_score=result["style_score"],
                glossary_score=result["glossary_score"],
                audiobook_score=result["audiobook_score"],
                verdict=result["verdict"],
                report_json=json.dumps(report),
            )
            result["created_at"] = ""  # DB will set this
        except Exception:
            pass  # If saving fails, still return the result
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
                qa_done += 1
                score = report.get("quality_score", 0)
                total_score += score
                verdict = str(report.get("verdict", "UNKNOWN") or "UNKNOWN")
                status = "pass" if verdict.upper() == "PASS" or score >= 6 else "fail"
                if status == "pass":
                    pass_count += 1
                else:
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
