from __future__ import annotations

import html
import importlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable


BACKEND_FALLBACK = "rule_based"
_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_DECORATION_RE = re.compile(r"[*_`>#~]+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "]+",
    flags=re.UNICODE,
)
_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ", ",
        "。": ". ",
        "！": "! ",
        "？": "? ",
        "；": "; ",
        "：": ": ",
        "、": ", ",
        "…": "...",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "—": " - ",
        "–": " - ",
    }
)
_COMMON_TERM_FIXES = {
    "kim đan": "Kim Đan",
    "nguyên anh": "Nguyên Anh",
    "trúc cơ": "Trúc Cơ",
    "luyện khí": "Luyện Khí",
    "hóa thần": "Hóa Thần",
    "linh thạch": "linh thạch",
    "đạo hữu": "đạo hữu",
}

_UNITS = ["", "nghìn", "triệu", "tỷ"]
_DIGIT_WORDS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


@dataclass(frozen=True)
class NormalizedText:
    text: str
    backend: str
    warnings: tuple[str, ...] = ()


def _read_three_digits(value: int, *, full: bool) -> str:
    hundred = value // 100
    ten = (value % 100) // 10
    unit = value % 10
    parts: list[str] = []
    if hundred > 0 or full:
        parts.append(_DIGIT_WORDS[hundred])
        parts.append("trăm")
    if ten > 1:
        parts.append(_DIGIT_WORDS[ten])
        parts.append("mươi")
        if unit == 1:
            parts.append("mốt")
        elif unit == 5:
            parts.append("lăm")
        elif unit:
            parts.append(_DIGIT_WORDS[unit])
    elif ten == 1:
        parts.append("mười")
        if unit == 5:
            parts.append("lăm")
        elif unit:
            parts.append(_DIGIT_WORDS[unit])
    elif unit:
        if hundred > 0 or full:
            parts.append("lẻ")
        parts.append(_DIGIT_WORDS[unit])
    return " ".join(parts).strip()


def number_to_vietnamese(value: int) -> str:
    if value == 0:
        return "không"
    if value < 0:
        return "âm " + number_to_vietnamese(abs(value))
    if value >= 1_000_000_000_000:
        return " ".join(_DIGIT_WORDS[int(digit)] for digit in str(value))
    groups: list[int] = []
    current = value
    while current:
        groups.append(current % 1000)
        current //= 1000
    parts: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        full = index != len(groups) - 1
        spoken = _read_three_digits(group, full=full)
        unit = _UNITS[index] if index < len(_UNITS) else ""
        parts.append(f"{spoken} {unit}".strip())
    return " ".join(parts)


def _normalize_chapter_numbers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return f"Chương {number_to_vietnamese(number)}"

    return re.sub(r"\bChương\s+(\d{1,6})\b", repl, text, flags=re.IGNORECASE)


def _normalize_inline_numbers(text: str) -> str:
    def date_words(match):
        from datetime import date
        day, month, year = (int(value) for value in match.groups())
        try:
            date(year, month, day)
        except ValueError:
            return match.group(0)
        return f"ngày {number_to_vietnamese(day)} tháng {number_to_vietnamese(month)} năm {number_to_vietnamese(year)}"

    text = re.sub(r"(?<![\w/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\w/])", date_words, text)
    text = re.sub(r"ngày\s+ngày\s+", "ngày ", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)(kg|km|cm|mm|ml|mg|%)(?=\W|$)", r"\1 \2", text, flags=re.IGNORECASE)
    def repl(match):
        raw = match.group(0)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
            return number_to_vietnamese(int(raw.replace(".", "")))
        if "," in raw or "." in raw:
            if raw.count(",") + raw.count(".") > 1:
                return raw
            integer, fraction = re.split(r"[.,]", raw, maxsplit=1)
            return number_to_vietnamese(int(integer)) + " phẩy " + " ".join(_DIGIT_WORDS[int(n)] for n in fraction)
        digits = raw.lstrip("-")
        if (len(digits) > 1 and digits.startswith("0")) or len(digits) > 12:
            return ("âm " if raw.startswith("-") else "") + " ".join(_DIGIT_WORDS[int(n)] for n in digits)
        return number_to_vietnamese(int(raw))

    return re.sub(r"(?<![\w./])-?\d+(?:[.,]\d+)*(?![\w/]|\.\d)", repl, text)


def _load_backend(backend: str) -> Callable[[str], str] | None:
    normalized = backend.strip().lower()
    if normalized in {"", BACKEND_FALLBACK, "rule", "rules"}:
        return None
    if normalized == "vinorm":
        try:
            module = importlib.import_module("vinorm")
        except ImportError:
            return None
        for name in ("TTSnorm", "normalize", "norm"):
            fn = getattr(module, name, None)
            if callable(fn):
                return lambda text, fn=fn: str(fn(text))
        return None
    if normalized in {"vietnormalizer", "viet_normalizer"}:
        for module_name in ("viet_normalizer", "VietNormalizer", "vietnormalizer"):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            for name in ("normalize", "Normalize", "text_normalize"):
                fn = getattr(module, name, None)
                if callable(fn):
                    return lambda text, fn=fn: str(fn(text))
        return None
    return None


def _finalize_spacing(text: str) -> str:
    value = re.sub(r"\s+([,.;:!?])", r"\1", text)
    value = re.sub(r"([,.;:!?])(?!\d)(?=\S)", r"\1 ", value)
    value = re.sub(r"([.!?])(?:\s+\1)+", r"\1", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def rule_based_normalize(text: str, *, convert_numbers: bool = True) -> str:
    value = html.unescape(text or "")
    value = _TAG_RE.sub(" ", value)
    value = _MARKDOWN_LINK_RE.sub(r"\1", value)
    value = _MARKDOWN_DECORATION_RE.sub(" ", value)
    value = _CONTROL_RE.sub(" ", value)
    value = _EMOJI_RE.sub(" ", value)
    value = unicodedata.normalize("NFC", value)
    value = value.translate(_PUNCT_TRANSLATION)
    value = re.sub(r"\.{4,}", "...", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = _normalize_chapter_numbers(value)
    if convert_numbers:
        value = _normalize_inline_numbers(value)
    for source, target in _COMMON_TERM_FIXES.items():
        value = re.sub(rf"\b{re.escape(source)}\b", target, value, flags=re.IGNORECASE)
    return _finalize_spacing(value)


def normalize_text(text: str, backend: str = "vinorm") -> NormalizedText:
    warnings: list[str] = []
    base = rule_based_normalize(text, convert_numbers=False)
    backend_fn = _load_backend(backend)
    if backend_fn is not None:
        try:
            normalized = rule_based_normalize(backend_fn(base), convert_numbers=False)
            return NormalizedText(text=normalized, backend=backend.strip().lower(), warnings=())
        except Exception:
            warnings.append(f"{backend} failed; used rule-based normalizer")
    else:
        requested = backend.strip().lower()
        if requested and requested not in {BACKEND_FALLBACK, "rule", "rules"}:
            warnings.append(f"{backend} unavailable; used rule-based normalizer")
    return NormalizedText(text=rule_based_normalize(base, convert_numbers=True), backend=BACKEND_FALLBACK, warnings=tuple(warnings))
