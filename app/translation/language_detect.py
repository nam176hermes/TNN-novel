"""Simple language detection for novel text.

LibreTranslate uses langdetect + confidence scoring. For novel_pipeline,
we only need robust detection of Chinese / Vietnamese / mixed / unknown.
"""

from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
VI_RE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)
LATIN_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> dict:
    """Detect whether text is Chinese, Vietnamese, mixed, or unknown.

    Returns: {language, confidence, cjk_chars, vi_chars, latin_chars}
    """
    if not text or not text.strip():
        return {"language": "unknown", "confidence": 0.0, "cjk_chars": 0, "vi_chars": 0, "latin_chars": 0}

    cjk = len(CJK_RE.findall(text))
    vi = len(VI_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    total_signal = cjk + vi + latin
    if total_signal == 0:
        return {"language": "unknown", "confidence": 0.0, "cjk_chars": cjk, "vi_chars": vi, "latin_chars": latin}

    cjk_ratio = cjk / total_signal
    vi_ratio = vi / total_signal

    if cjk_ratio > 0.6:
        lang = "zh"
        conf = round(cjk_ratio * 100, 1)
    elif vi_ratio > 0.15 and cjk == 0:
        lang = "vi"
        conf = round(min(100, (vi_ratio + 0.5) * 100), 1)
    elif cjk > 0 and (vi > 0 or latin > 20):
        lang = "mixed"
        conf = round(max(cjk_ratio, vi_ratio) * 100, 1)
    else:
        lang = "unknown"
        conf = round(max(cjk_ratio, vi_ratio) * 100, 1)

    return {"language": lang, "confidence": conf, "cjk_chars": cjk, "vi_chars": vi, "latin_chars": latin}


def has_leftover_chinese(text: str) -> bool:
    """True if translated text still contains CJK characters."""
    return bool(CJK_RE.search(text or ""))


def count_leftover_chinese(text: str) -> int:
    """Count CJK characters left in translated text."""
    return len(CJK_RE.findall(text or ""))
