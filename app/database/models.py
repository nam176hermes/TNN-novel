from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ChapterStatus(str, Enum):
    IMPORTED = "imported"
    CLEANED = "cleaned"
    TRANSLATED = "translated"
    QA_DONE = "qa_done"
    AUDIO_DONE = "audio_done"
    FAILED = "failed"


class Book(BaseModel):
    id: Optional[int] = None
    title: str
    author: str = ""
    source: str = "manual"
    source_url: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Chapter(BaseModel):
    id: Optional[int] = None
    book_id: int
    chapter_number: int
    title: str
    source_url: str = ""
    adapter_id: str = ""
    raw_text_path: Optional[Path] = None
    cleaned_text_path: Optional[Path] = None
    translated_text_path: Optional[Path] = None
    content_html_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    status: ChapterStatus = ChapterStatus.IMPORTED
    imported_at: datetime = Field(default_factory=datetime.utcnow)
    translated_at: Optional[datetime] = None
    audio_created_at: Optional[datetime] = None


class GlossaryTerm(BaseModel):
    id: Optional[int] = None
    book_id: int
    source_term: str
    target_term: str
    category: str = "term"
    confidence: float = 1.0
    approved: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QAReport(BaseModel):
    id: Optional[int] = None
    chapter_id: int
    quality_score: float
    report_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderProgress(BaseModel):
    book_id: int
    chapter_id: int
    mode: str = "scroll"
    percent: int = 0
    paragraph_index: int = 0
    char_offset: int = 0
    absolute_char_offset: int = 0
    page_index: int = 0
    anchor: dict = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReaderAnnotation(BaseModel):
    id: Optional[int] = None
    book_id: int
    chapter_id: int
    kind: str
    paragraph_index: int = 0
    char_start: int = 0
    char_end: int = 0
    selected_text: str = ""
    note: str = ""
    color: str = "yellow"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None
