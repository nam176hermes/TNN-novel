from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.utils.chinese_numbers import parse_chinese_number


def source_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def clean_book_title(title: str) -> str:
    cleaned = title.strip()
    cleaned = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", cleaned)
    cleaned = re.sub(r"\[(?:raw|txt|source|cn|zh)\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\((?:raw|txt|source|cn|zh)\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("《》「」『』[]()（） \t\r\n")
    cleaned = re.sub(r"[_-]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_book_key(title: str) -> str:
    cleaned = clean_book_title(title).casefold()
    return re.sub(r"[\W_]+", "", cleaned, flags=re.UNICODE)


def _parse_chinese_number(value: str) -> int | None:
    return parse_chinese_number(value)


def _chapter_from_text_line(line: str) -> tuple[int | None, str]:
    patterns = [
        r"^\s*第\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[章节回卷]\s*(.*)$",
        r"^\s*Ch(?:apter)?\.?\s*([0-9]+)\s*[:：.\-\s]*(.*)$",
        r"^\s*Chương\s*([0-9]+)\s*[:：.\-\s]*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, line, flags=re.IGNORECASE)
        if match:
            return _parse_chinese_number(match.group(1)), match.group(2).strip()
    return None, ""


def detect_import_metadata(
    *,
    title: str = "",
    chapter_number: int | None = None,
    chapter_title: str = "",
    text: str = "",
    filename: str = "",
) -> dict:
    detected_title = clean_book_title(title)
    detected_chapter_number = chapter_number if chapter_number and chapter_number > 0 else 1
    detected_chapter_title = chapter_title.strip()

    if filename:
        stem = Path(filename).name
        stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", stem)
        match = re.match(
            r"^\s*(.+?)\s*[-_]\s*(?:Chương|Chapter|Ch\.?|第)\s*([0-9]+|[零〇一二两三四五六七八九十百千万]+)\s*[-_：:\s]*(.*)$",
            stem,
            flags=re.IGNORECASE,
        )
        if match:
            detected_title = detected_title or clean_book_title(match.group(1))
            parsed = _parse_chinese_number(match.group(2))
            detected_chapter_number = parsed or detected_chapter_number
            detected_chapter_title = detected_chapter_title or match.group(3).strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        if not detected_title:
            title_match = re.match(r"^《(.+?)》$", line)
            if title_match:
                detected_title = clean_book_title(title_match.group(1))
                continue

        parsed_number, parsed_title = _chapter_from_text_line(line)
        if parsed_number is not None:
            detected_chapter_number = parsed_number
            if not detected_chapter_title:
                detected_chapter_title = parsed_title
            break

    return {
        "title": detected_title,
        "book_key": normalize_book_key(detected_title),
        "chapter_number": detected_chapter_number,
        "chapter_title": detected_chapter_title,
        "source_hash": source_hash(text),
    }
