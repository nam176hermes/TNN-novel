from __future__ import annotations

from datetime import datetime

from app.database.models import Book, Chapter, ChapterStatus, GlossaryTerm, QAReport


class TestChapterStatus:
    def test_enum_values(self):
        assert ChapterStatus.IMPORTED.value == "imported"
        assert ChapterStatus.CLEANED.value == "cleaned"
        assert ChapterStatus.TRANSLATED.value == "translated"
        assert ChapterStatus.QA_DONE.value == "qa_done"
        assert ChapterStatus.AUDIO_DONE.value == "audio_done"
        assert ChapterStatus.FAILED.value == "failed"

    def test_enum_membership(self):
        assert "imported" in [s.value for s in ChapterStatus]


class TestBookModel:
    def test_defaults(self):
        book = Book(title="仙侠世界")
        assert book.title == "仙侠世界"
        assert book.author == ""
        assert book.source == "manual"
        assert book.source_url == ""
        assert book.id is None
        assert isinstance(book.created_at, datetime)

    def test_with_all_fields(self):
        book = Book(
            id=1,
            title="Test",
            author="Author",
            source="web",
            source_url="http://example.com",
        )
        assert book.id == 1
        assert book.author == "Author"

    def test_serialization(self):
        book = Book(title="测试")
        d = book.model_dump()
        assert d["title"] == "测试"
        assert "created_at" in d


class TestChapterModel:
    def test_defaults(self):
        ch = Chapter(book_id=1, chapter_number=1, title="第一章")
        assert ch.status == ChapterStatus.IMPORTED
        assert ch.source_url == ""
        assert ch.adapter_id == ""
        assert ch.raw_text_path is None
        assert ch.cleaned_text_path is None
        assert ch.translated_text_path is None
        assert ch.audio_path is None
        assert ch.translated_at is None

    def test_with_all_fields(self):
        from pathlib import Path
        ch = Chapter(
            id=1,
            book_id=1,
            chapter_number=2,
            title="第二章",
            source_url="http://example.com/2",
            adapter_id="generic_html",
            raw_text_path=Path("/tmp/raw.txt"),
            cleaned_text_path=Path("/tmp/clean.txt"),
            status=ChapterStatus.TRANSLATED,
        )
        assert ch.status == ChapterStatus.TRANSLATED
        assert ch.adapter_id == "generic_html"
        assert str(ch.raw_text_path) == "/tmp/raw.txt"


class TestGlossaryTermModel:
    def test_defaults(self):
        gt = GlossaryTerm(book_id=1, source_term="灵石", target_term="linh thạch")
        assert gt.category == "term"
        assert gt.confidence == 1.0
        assert gt.approved is True
        assert gt.id is None

    def test_with_bool_approved(self):
        gt = GlossaryTerm(book_id=1, source_term="A", target_term="B", approved=False)
        assert gt.approved is False


class TestQAReportModel:
    def test_defaults(self):
        report = QAReport(chapter_id=1, quality_score=8.5, report_json="{}")
        assert report.chapter_id == 1
        assert report.quality_score == 8.5
        assert isinstance(report.created_at, datetime)
