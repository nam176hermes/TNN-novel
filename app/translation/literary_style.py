from __future__ import annotations

import re

from app.translation.styleguide_config import get_literary_phrase_pairs, get_literary_style_guide_lines


LITERARY_STYLE_GUIDE = "\n".join(f"- {line}" for line in get_literary_style_guide_lines())

_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "、": ",",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def _matchable_text(text: str) -> str:
    normalized = text.translate(_PUNCTUATION_TRANSLATION)
    return re.sub(r"\s+", "", normalized)


def phrase_in_source(phrase: str, source_text: str) -> bool:
    if not phrase or not source_text:
        return False
    return _matchable_text(phrase) in _matchable_text(source_text)


def matching_literary_phrase_pairs(source_text: str, limit: int = 16) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for source, target in get_literary_phrase_pairs():
        if phrase_in_source(source, source_text):
            matches.append((source, target))
        if len(matches) >= limit:
            break
    return matches


def render_literary_phrase_guide(source_text: str, limit: int = 16) -> str:
    lines = ["Literary phrase guide:", LITERARY_STYLE_GUIDE.strip(), "", "Relevant phrase examples:"]
    matches = matching_literary_phrase_pairs(source_text, limit=limit)
    if matches:
        lines.extend(f"- {source} -> {target}" for source, target in matches)
    else:
        lines.append("- (none detected in this chunk)")
    return "\n".join(lines)
