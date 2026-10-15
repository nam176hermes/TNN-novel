"""Compatibility exports; metadata belongs to the ingestion domain."""
from app.ingestion import import_metadata as _metadata

clean_book_title = _metadata.clean_book_title
normalize_book_key = _metadata.normalize_book_key
detect_import_metadata = _metadata.detect_import_metadata
_parse_chinese_number = _metadata._parse_chinese_number
_chapter_from_text_line = _metadata._chapter_from_text_line
normalize_import_text = _metadata.normalize_import_text
source_hash = _metadata.source_hash
