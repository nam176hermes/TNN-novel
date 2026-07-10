"""
Deterministic pre-translator — QuickTranslator-inspired greedy max-match engine.

Handles three tasks in one pass:
1. Hán-Việt char transliteration (fallback)
2. Greedy longest-phrase match with embedded longer rejection
3. Name/entity protection to prevent swallowing

Results: Pre-translated text with marked spans. Only unmapped segments
go to Ollama for LLM translation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

MAX_PHRASE_LENGTH = 20

# Known Sino-Vietnamese surnames (used for name protection pronoun rules)
PROTECTED_SURNAMES: Set[str] = {
    "Nguyên", "Hàn", "Kim", "Lý", "Trần", "Vương", "Triệu",
    "La", "Tống", "Đỗ", "Phạm", "Hoàng", "Đường", "Tạ",
    "Bạch", "Diệp", "Lâm", "Mạc", "Tô", "Tôn", "Chu",
}


@dataclass
class TranslationToken:
    """Single translated segment with full provenance metadata.

    Ported from QuickTranslator's CharRange alignment arrays.
    """
    src_start: int
    src_end: int
    tgt_start: int
    tgt_end: int
    src_text: str
    tgt_text: str
    kind: str = "char"  # "phrase", "name", "rule", "char", "literal"
    candidates: List[str] = field(default_factory=list)


@dataclass
class Lexicon:
    """Multi-layer dictionary stack with priority tiers.

    Ported from QuickTranslator's dictionary architecture:
    Names → Phrases → Char fallback.
    """
    name_dict: Dict[str, str] = field(default_factory=dict)
    phrase_dict: Dict[str, str] = field(default_factory=dict)
    char_dict: Dict[str, str] = field(default_factory=dict)
    combine_views: bool = True
    _combined: Dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.combine_views:
            self._rebuild_combined()

    def _rebuild_combined(self) -> None:
        """Rebuild combined dict: names win over phrases wins over chars."""
        result = {}
        # Names highest priority
        for k, v in self.name_dict.items():
            result[k] = v
        # Phrases next
        for k, v in self.phrase_dict.items():
            if k not in result:
                result[k] = v
        # Chars (single CJK) lowest
        for k, v in self.char_dict.items():
            if k not in result:
                result[k] = v
        self._combined = result

    def add_name(self, src: str, tgt: str) -> None:
        self.name_dict[src] = tgt
        if self.combine_views:
            self._combined[src] = tgt

    def add_phrase(self, src: str, tgt: str) -> None:
        self.phrase_dict[src] = tgt
        if self.combine_views and src not in self.name_dict:
            self._combined[src] = tgt

    def add_char(self, ch: str, tgt: str) -> None:
        """Add a single CJK character mapping."""
        self.char_dict[ch] = tgt
        if self.combine_views and ch not in self.name_dict and ch not in self.phrase_dict:
            self._combined[ch] = tgt

    def lookup(self, text: str) -> Optional[str]:
        return self._combined.get(text)

    def contains_name(self, text: str) -> bool:
        """Check if text exactly matches a known name."""
        return text in self.name_dict

    def name_in_span(self, text: str, start: int, length: int) -> bool:
        """Check if a known name starts inside (or overlaps) span [start, start+length).
        Ported from QuickTranslator's containsName().
        The span itself is NOT the name - we check for NAMES inside the span.
        """
        if length < 2:
            return False
        # If the entire span IS a name, it's allowed (not rejected)
        if text[start:start + length] in self.name_dict:
            return False
        # Check for name starting inside span
        end = start + length - 1  # don't check at very end
        for pos in range(start + 1, end + 1):
            max_check = min(MAX_PHRASE_LENGTH, len(text) - pos)
            for L in range(max_check, 1, -1):
                if text[pos:pos + L] in self.name_dict:
                    return True
        return False

    def is_longest_in_sentence(
        self, text: str, start: int, phrase_len: int,
        algorithm: int = 0,
    ) -> bool:
        """Embedded longer phrase rejection.
        Ported from QuickTranslator's isLongestPhraseInSentence().
        Checks if a longer phrase exists starting inside the current candidate.
        """
        if phrase_len < 2:
            return True
        threshold = phrase_len if algorithm == 0 else max(3, phrase_len)
        end = start + phrase_len - 1
        for pos in range(start + 1, end + 1):
            max_check = min(MAX_PHRASE_LENGTH, len(text) - pos)
            for L in range(max_check, threshold, -1):
                candidate = text[pos:pos + L]
                if candidate in self._combined:
                    return False
        return True


def build_lexicon_from_glossary(
    glossary: Dict[str, str],
    name_map: Dict[str, str],
    char_dict: Optional[Dict[str, str]] = None,
) -> Lexicon:
    """Build Lexicon from pipeline glossary dicts."""
    lex = Lexicon(char_dict=char_dict or {})

    # Name map entries → name_dict
    for src, tgt in name_map.items():
        if src and tgt:
            lex.add_name(src, tgt)

    # Glossary translate-mode entries → phrase_dict
    # (entries already in name_map skip phrase_dict via _rebuild_combined)
    for src, tgt in glossary.items():
        if src and tgt:
            # Multi-meaning: only first for deterministic
            primary = tgt.split("/")[0].split("|")[0].strip()
            lex.add_phrase(src, primary)

    return lex


def to_narrow(text: str) -> str:
    """Convert fullwidth ASCII characters to halfwidth.
    Ported from QuickTranslator's ToNarrow().
    """
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(" ")
        else:
            result.append(ch)
    return "".join(result)


def pretranslate(
    text: str,
    lexicon: Lexicon,
    algorithm: int = 0,
    prioritize_names: bool = True,
    check_longest: bool = True,
) -> Tuple[str, List[TranslationToken]]:
    """Greedy max-match pre-translation with name protection + embedded rejection.

    Ported from QuickTranslator's ChineseToVietPhrase() core algorithm.

    Args:
        text: Source Chinese text
        lexicon: Multi-layer dictionary
        algorithm: 0=full check, 1/2=shortcut check
        prioritize_names: Enable name protection (prevents phrase swallowing names)
        check_longest: Enable embedded longer phrase rejection

    Returns:
        (translated_text, list[TranslationToken])
    """
    out: List[str] = []
    tokens: List[TranslationToken] = []
    i = 0
    tgt_pos = 0

    while i < len(text):
        ch = text[i]
        matched = False

        # Phase 1: Try phrase/name lookups (greedy descending)
        max_check = min(MAX_PHRASE_LENGTH, len(text) - i)
        for L in range(max_check, 1, -1):
            phrase = text[i:i + L]

            if phrase in lexicon._combined:
                # Name protection: reject phrase if it contains a known name inside
                if prioritize_names and lexicon.name_in_span(text, i, L):
                    continue

                # Embedded longer rejection: check if longer phrase starts inside
                if check_longest and not lexicon.is_longest_in_sentence(text, i, L, algorithm):
                    continue

                tgt = lexicon._combined[phrase]
                out.append(tgt)
                tokens.append(TranslationToken(
                    src_start=i, src_end=i + L,
                    tgt_start=tgt_pos, tgt_end=tgt_pos + len(tgt),
                    src_text=phrase, tgt_text=tgt,
                    kind="name" if phrase in lexicon.name_dict else "phrase",
                ))
                tgt_pos += len(tgt)
                i += L
                matched = True
                break

        if not matched:
            # Phase 2: Char-level Hán-Việt fallback
            if ch in lexicon.char_dict:
                tgt = lexicon.char_dict[ch]
                out.append(tgt)
                tokens.append(TranslationToken(
                    src_start=i, src_end=i + 1,
                    tgt_start=tgt_pos, tgt_end=tgt_pos + len(tgt),
                    src_text=ch, tgt_text=tgt,
                    kind="char",
                ))
                tgt_pos += len(tgt)
            else:
                # Phase 3: Literal pass-through
                narrow = to_narrow(ch)
                out.append(narrow)
                tokens.append(TranslationToken(
                    src_start=i, src_end=i + 1,
                    tgt_start=tgt_pos, tgt_end=tgt_pos + len(narrow),
                    src_text=ch, tgt_text=narrow,
                    kind="literal",
                ))
                tgt_pos += len(narrow)
            i += 1

    return "".join(out), tokens


def tokenize_untranslated_spans(
    text: str,
    translated: str,
    tokens: List[TranslationToken],
) -> List[dict]:
    """Extract spans that were NOT handled by pre-translator (for Ollama fallback).

    A span is "untranslated" if the token kind is "char" or "literal".
    Returns list of dicts with src_text, translated section context.
    """
    untranslated = []
    for tok in tokens:
        if tok.kind in ("char", "literal"):
            untranslated.append({
                "src_start": tok.src_start,
                "src_end": tok.src_end,
                "src_text": tok.src_text,
                "context_before": text[max(0, tok.src_start - 30):tok.src_start],
                "context_after": text[tok.src_end:tok.src_end + 30],
                "kind": tok.kind,
            })
    return untranslated


def get_protected_spans(text: str, name_dict: Dict[str, str]) -> List[Tuple[int, int]]:
    """Find all name/entity spans in text for protection markers.
    Ported from QuickTranslator's containsName() for pre-scan phase.

    Returns sorted list of (start, end) positions.
    """
    spans: List[Tuple[int, int]] = []
    if not name_dict:
        return spans

    # Sort by length descending for greedy matching
    names_sorted = sorted(name_dict.keys(), key=len, reverse=True)
    occupied: Set[int] = set()

    # Greedy longest match for names
    i = 0
    while i < len(text):
        best_end = None
        for name in names_sorted:
            if text.startswith(name, i):
                # Check this span doesn't overlap already occupied
                overlap = any(pos in occupied for pos in range(i, i + len(name)))
                if not overlap and len(name) >= 2:
                    best_end = i + len(name)
        if best_end:
            for pos in range(i, best_end):
                occupied.add(pos)
            spans.append((i, best_end))
            i = best_end
        else:
            i += 1

    return spans


def apply_protection_markers(text: str, spans: List[Tuple[int, int]]) -> str:
    """Wrap protected spans with sentinel markers so template rules skip them."""
    if not spans:
        return text
    # Apply from right to left to preserve positions
    result = list(text)
    for start, end in reversed(spans):
        # Mark span boundaries with invisible sentinel (zero-width space)
        # Template engine checks for these
        result.insert(end, "\u200C")
        result.insert(start, "\u200C")
    return "".join(result)
