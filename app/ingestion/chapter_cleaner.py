from __future__ import annotations

import re

BLANK_RE = re.compile(r"^\s*$")

# Lines that look like HTML/JS/template boilerplate
BOILERPLATE_RE = re.compile(
    r"^\s*</?(?:html|head|body|div|span|p|a|script|style|br|hr|meta|link|img|iframe|"
    r"nav|footer|header|section|article|aside|ul|ol|li|form|input|button|table|tr|td|th|h[1-6])\b",
    re.IGNORECASE,
)

# Lines that are pure punctuation / numbers (<4 chars, no CJK)
JUNK_RE = re.compile(r"^[\s\d\W]{1,3}$")

# CJK character detection
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def clean_chapter(raw: str) -> str:
    """Remove boilerplate junk, collapse blank lines, trim whitespace."""
    lines = raw.splitlines()
    kept: list[str] = []

    for line in lines:
        stripped = line.strip()
        if BLANK_RE.match(stripped):
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if BOILERPLATE_RE.match(stripped):
            continue
        if len(stripped) < 4 and not _has_cjk(stripped):
            continue
        if JUNK_RE.match(stripped):
            continue
        kept.append(stripped)

    return "\n".join(kept).strip()