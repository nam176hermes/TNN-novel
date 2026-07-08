from __future__ import annotations

import re
from dataclasses import dataclass


_SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"')\]\}»”’]*")
_QUOTE_CHARS = {'"', "'", "“", "”", "‘", "’", "«", "»"}


@dataclass(frozen=True)
class TTSChunk:
    chapter_id: int | None
    chunk_index: int
    text: str
    normalized_text: str
    start_char: int
    end_char: int


def _quote_balanced(text: str) -> bool:
    double_count = sum(1 for char in text if char in {'"', "“", "”", "«", "»"})
    single_count = sum(1 for char in text if char in {"'", "‘", "’"})
    return double_count % 2 == 0 and single_count % 2 == 0


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    quote_open = False
    for index, char in enumerate(text):
        if char in _QUOTE_CHARS:
            quote_open = not quote_open
        if _SENTENCE_END_RE.match(text, index):
            match = _SENTENCE_END_RE.match(text, index)
            if match is None:
                continue
            end = match.end()
            candidate = text[start:end].strip()
            if candidate and (not quote_open or _quote_balanced(candidate)):
                spans.append((start, end))
                start = end
    if start < len(text):
        tail = text[start:].strip()
        if tail:
            offset = len(text[start:]) - len(text[start:].lstrip())
            spans.append((start + offset, len(text)))
    return spans


def _paragraph_sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in re.finditer(r"\n\s*\n", text):
        paragraph = text[cursor:match.start()]
        spans.extend((cursor + start, cursor + end) for start, end in _sentence_spans(paragraph))
        cursor = match.end()
    if cursor < len(text):
        spans.extend((cursor + start, cursor + end) for start, end in _sentence_spans(text[cursor:]))
    return spans


def _split_long_span(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        hard_end = min(end, cursor + max_chars)
        if hard_end >= end:
            spans.append((cursor, end))
            break
        window = text[cursor:hard_end]
        split_at = max(
            window.rfind("; "),
            window.rfind(", "),
            window.rfind(" - "),
            window.rfind(" "),
        )
        if split_at < max_chars // 3:
            split_at = max_chars
        next_end = min(end, cursor + split_at)
        spans.append((cursor, next_end))
        cursor = next_end
        while cursor < end and text[cursor].isspace():
            cursor += 1
    return spans


def chunk_text(
    text: str,
    *,
    chapter_id: int | None = None,
    max_chars: int = 450,
    max_sentences: int = 4,
) -> list[TTSChunk]:
    clean_text = (text or "").strip()
    if not clean_text:
        return []
    max_chars = max(80, int(max_chars or 450))
    max_sentences = max(1, int(max_sentences or 4))

    sentence_spans: list[tuple[int, int]] = []
    for start, end in _paragraph_sentence_spans(clean_text):
        if end - start > max_chars:
            sentence_spans.extend(_split_long_span(clean_text, start, end, max_chars))
        else:
            sentence_spans.append((start, end))
    if not sentence_spans:
        sentence_spans = _split_long_span(clean_text, 0, len(clean_text), max_chars)

    chunks: list[TTSChunk] = []
    current_spans: list[tuple[int, int]] = []

    def flush() -> None:
        if not current_spans:
            return
        start = current_spans[0][0]
        end = current_spans[-1][1]
        chunk_text_value = clean_text[start:end].strip()
        chunks.append(
            TTSChunk(
                chapter_id=chapter_id,
                chunk_index=len(chunks),
                text=chunk_text_value,
                normalized_text=chunk_text_value,
                start_char=start,
                end_char=end,
            )
        )
        current_spans.clear()

    for span in sentence_spans:
        proposed = current_spans + [span]
        proposed_start = proposed[0][0]
        proposed_end = proposed[-1][1]
        too_long = proposed_end - proposed_start > max_chars
        too_many = len(proposed) > max_sentences
        if current_spans and (too_long or too_many):
            flush()
        current_spans.append(span)
    flush()
    return chunks
