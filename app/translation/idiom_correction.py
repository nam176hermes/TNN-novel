"""Idiom correction layer — fixes common Chinese→Vietnamese idiom translation errors.

Adapted from Grok review findings. Applied after main post-processing.

⚠️ IMPORTANT: All corrections must produce PURE Vietnamese output.
No mixed Chinese/Vietnamese entries allowed.
"""

from __future__ import annotations

import re
import unicodedata

from app.translation.styleguide_config import (
    get_literary_phrase_pairs,
)
from app.translation.style_rule_engine import normalize_style_rule_text

# Chinese idiom → correct Vietnamese idiom
IDIOM_CORRECTIONS = {
    # 瘦死的骆驼比马大 – The dying camel is still bigger than the horse
    r"瘦死.{0,2}骆驼.{0,2}比.{0,2}马大": "Lạc đà chết vẫn to hơn ngựa",
    r"Ngựa chết.{0,2}còn.{0,2}to.{0,2}hơn.{0,2}voi": "Lạc đà chết vẫn to hơn ngựa",
    r"Ngựa chết.{0,2}da.{0,2}còn.{0,2}to.{0,2}hơn.{0,2}voi": "Lạc đà chết vẫn to hơn ngựa",
    r"Ngựa chết.{0,2}da.{0,2}còn.{0,2}to.{0,2}hơn.{0,2}lừa": "Lạc đà chết vẫn to hơn ngựa",
    r"Lạc đà.{0,5}gầy.{0,5}vẫn.{0,5}[Ll]ớn.{0,5}hơn.{0,5}ngựa": "Lạc đà chết vẫn to hơn ngựa",

    # Common xianxia idioms (pure Vietnamese output only)
    r"三百六十行，行行出状元": "Ba trăm sáu mươi nghề, nghề nào cũng có người giỏi",
    r"百尺竿头，更进一步": "Trăm thước càng tiến lên cao, càng phải tiến xa hơn",
    r"初生牛犊不怕虎": "Trâu non không sợ hổ",
}

# Pattern-based corrections (more flexible, pure Vietnamese output only)
IDIOM_PATTERNS = [
    # 瘦死的骆驼比马大 variants
    (re.compile(r"Lạc đà.{0,5}gầy.{0,5}vẫn.{0,5}lớn.{0,5}hơn.{0,5}ngựa", re.IGNORECASE),
     "Lạc đà chết vẫn to hơn ngựa"),
    (re.compile(r"Ngựa chết.{0,8}còn.{0,8}to.{0,8}hơn.{0,8}voi", re.IGNORECASE),
     "Lạc đà chết vẫn to hơn ngựa"),
    (re.compile(r"Lạc đà.{0,5}gầy.{0,5}còn.{0,5}to.{0,5}hơn.{0,5}ngựa", re.IGNORECASE),
     "Lạc đà chết vẫn to hơn ngựa"),
]


def correct_idioms(text: str) -> str:
    """Apply idiom corrections to translated text."""
    for wrong, correct in IDIOM_CORRECTIONS.items():
        if wrong in text:
            text = text.replace(wrong, correct)
    for pattern, correct in IDIOM_PATTERNS:
        text = pattern.sub(correct, text)
    return text


def correct_chinese_idioms_in_translation(text: str) -> str:
    """Correct Chinese idioms that leaked through translation.

    Only applies to 100% Vietnamese corrections. All entries must be
    verified pure Vietnamese output.
    """
    corrections = {
        "瘦死的骆驼比马大": "Lạc đà chết vẫn to hơn ngựa",
        "三百六十行": "Ba trăm sáu mươi nghề",
        "百尺竿头": "Trăm thước càng tiến lên cao",
        "初生牛犊不怕虎": "Trâu non không sợ hổ",
    }
    for chinese, vietnamese in get_literary_phrase_pairs():
        corrections.setdefault(chinese, vietnamese)
    for chinese, vietnamese in corrections.items():
        if chinese in text:
            text = text.replace(chinese, vietnamese)
    return text


def fix_known_translation_errors(text: str) -> str:
    """Fix specific known translation errors from Grok review."""
    fixes = {
        "cháu nội": "cháu trai ruột",
        "đại lâu": "tửu lâu",
        "Đại lâu": "Tửu lâu",
        "tiểu thi": "tiểu nhị",
        "Tiểu thi": "Tiểu nhị",
    }
    for wrong, correct in fixes.items():
        text = text.replace(wrong, correct)
    return text


_VIETNAMESE_ACCENT_CHARS = (
    "àáảãạăằắẳẵặâầấẩẫậ"
    "èéẻẽẹêềếểễệ"
    "ìíỉĩị"
    "òóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữự"
    "ỳýỷỹỵ"
    "đ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬ"
    "ÈÉẺẼẸÊỀẾỂỄỆ"
    "ÌÍỈĨỊ"
    "ÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    "ÙÚỦŨỤƯỪỨỬỮỰ"
    "ỲÝỶỸỴ"
    "Đ"
)
_SPLIT_SYLLABLE_RE = re.compile(
    rf"\b([A-Za-zÀ-ỹĐđ]*[{re.escape(_VIETNAMESE_ACCENT_CHARS)}][A-Za-zÀ-ỹĐđ]*)\s+"
    r"(ng|nh|ch|c|i|m|n|p|t|u|y)\b"
)
_HEADING_RE = re.compile(r"^(Chương\s+\d+\s*[:：]\s*)(.+)$", flags=re.IGNORECASE)
_HEADING_BODY_STARTERS = (
    "hắn",
    "nàng",
    "ngay",
    "gần",
    "trên",
    "một",
    "trong",
    "sau",
    "khi",
    "đây",
    "lúc",
    "lý",
    "trần",
    "tòa",
    "thành",
)


def _collapse_split_vietnamese_syllables(text: str) -> str:
    previous = ""
    while previous != text:
        previous = text
        text = _SPLIT_SYLLABLE_RE.sub(r"\1\2", text)
    return text


def _strip_duplicate_heading_prefix(title: str, body: str) -> str:
    title_words = re.findall(r"[A-Za-zÀ-ỹĐđ]+", title.casefold())
    if len(title_words) < 2:
        return body

    for size in range(min(6, len(title_words)), 1, -1):
        suffix = " ".join(title_words[-size:])
        pattern = re.compile(rf"^\s*{re.escape(suffix)}(?:\s+|$)", flags=re.IGNORECASE)
        if pattern.search(body.casefold()):
            return re.sub(rf"^\s*{re.escape(suffix)}(?:\s+|$)", "", body, count=1, flags=re.IGNORECASE).lstrip()
    return body


def _split_glued_heading_body(text: str) -> str:
    lines = text.split("\n", 1)
    first_line = lines[0].strip()
    rest = lines[1] if len(lines) > 1 else ""
    heading_match = _HEADING_RE.match(first_line)
    if not heading_match or len(first_line) > 180:
        return text

    heading_prefix = heading_match.group(1)
    heading_text = heading_match.group(2).strip()
    heading_text_lower = heading_text.casefold()
    glued_candidates: list[int] = []
    for starter in _HEADING_BODY_STARTERS:
        candidate = heading_text_lower.rfind(starter)
        if candidate > 0 and not heading_text[candidate - 1].isspace():
            glued_candidates.append(candidate)
    split_at = max(glued_candidates) if glued_candidates else -1

    if split_at <= 8:
        return text

    title = heading_text[:split_at].rstrip()
    body = heading_text[split_at:].lstrip()
    if len(title.split()) < 2 or not body:
        return text

    body = _strip_duplicate_heading_prefix(title, "\n".join(part for part in (body, rest) if part).lstrip())
    if not body:
        return f"{heading_prefix}{title}".strip()
    return f"{heading_prefix}{title}\n\n{body}".strip()


def clean_translation_layout(text: str) -> str:
    """Normalize translation artifacts that affect reader, export, and TTS output."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = _collapse_split_vietnamese_syllables(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([.!?])(?=[A-ZÀ-ỸĐ])", r"\1 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _split_glued_heading_body(text)
    return text.strip()


def post_process_with_idioms(text: str) -> str:
    """Full post-processing with idiom corrections."""
    text = correct_idioms(text)
    text = correct_chinese_idioms_in_translation(text)
    text = normalize_style_rule_text(text)
    text = fix_known_translation_errors(text)
    return clean_translation_layout(text)
