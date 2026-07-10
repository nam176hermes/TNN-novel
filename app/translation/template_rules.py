"""
Template rules (Luật Nhân) — QuickTranslator-inspired pattern-based translation.

Handles structured patterns: chapter titles, honorifics, speaker tags, ordinals.
Runs after glossary pre-substitution, replaces pattern placeholders with
dictionary lookups. Zero LLM variance on these patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from app.translation.pre_translator import Lexicon


@dataclass
class TemplateRule:
    """Pattern-based translation rule with slot dictionary.

    Example:
        TemplateRule(src="第{0}章", dst="Chương {0}", slot="numbers")
        TemplateRule(src="{0}说道", dst="{0} nói", slot="names")
    """
    src: str
    dst: str
    slot: str = "all"   # "numbers", "names", "pronouns", "phrases", "all"


# Default rules ported from QuickTranslator's luatNhanDictionary + novel-specific
DEFAULT_RULES: List[TemplateRule] = [
    # Chapter/section headers
    TemplateRule(src=r"第(.+?)章", dst=r"Chương \1", slot="numbers"),
    TemplateRule(src=r"第(.+?)卷", dst=r"Quyển \1", slot="numbers"),
    TemplateRule(src=r"第(.+?)回", dst=r"Hồi \1", slot="numbers"),
    TemplateRule(src=r"第(.+?)节", dst=r"Tiết \1", slot="numbers"),

    # Speaker tags
    TemplateRule(src=r"(.+?)说道", dst=r"\1 nói", slot="names"),
    TemplateRule(src=r"(.+?)问道", dst=r"\1 hỏi", slot="names"),
    TemplateRule(src=r"(.+?)答道", dst=r"\1 đáp", slot="names"),
    TemplateRule(src=r"(.+?)冷声道", dst=r"\1 lạnh giọng nói", slot="names"),
    TemplateRule(src=r"(.+?)淡淡道", dst=r"\1 thản nhiên nói", slot="names"),
    TemplateRule(src=r"(.+?)笑道", dst=r"\1 cười nói", slot="names"),
    TemplateRule(src=r"(.+?)怒道", dst=r"\1 giận dữ nói", slot="names"),
    TemplateRule(src=r"(.+?)叹道", dst=r"\1 thở dài nói", slot="names"),
    TemplateRule(src=r"(.+?)喝道", dst=r"\1 quát", slot="names"),
    TemplateRule(src=r"(.+?)叫道", dst=r"\1 kêu lên", slot="names"),

    # Honorifics / titles
    TemplateRule(src=r"(.+?)师兄", dst=r"\1 sư huynh", slot="names"),
    TemplateRule(src=r"(.+?)师姐", dst=r"\1 sư tỷ", slot="names"),
    TemplateRule(src=r"(.+?)师弟", dst=r"\1 sư đệ", slot="names"),
    TemplateRule(src=r"(.+?)师妹", dst=r"\1 sư muội", slot="names"),
    TemplateRule(src=r"(.+?)前辈", dst=r"\1 tiền bối", slot="names"),
    TemplateRule(src=r"(.+?)道友", dst=r"\1 đạo hữu", slot="names"),
    TemplateRule(src=r"(.+?)兄", dst=r"\1 huynh", slot="names"),
    TemplateRule(src=r"(.+?)大人", dst=r"\1 đại nhân", slot="names"),

    # Cultivation / realm patterns
    TemplateRule(src=r"(.+?)境界", dst=r"\1 cảnh giới", slot="phrases"),
    TemplateRule(src=r"(.+?)期", dst=r"\1 kỳ", slot="phrases"),
    TemplateRule(src=r"(.+?)层", dst=r"tầng \1", slot="numbers"),

    # Ordinals
    TemplateRule(src=r"第(.+?)次", dst=r"lần thứ \1", slot="numbers"),
    TemplateRule(src=r"第(.+?)个", dst=r"thứ \1", slot="numbers"),
    TemplateRule(src=r"第(.+?)名", dst=r"hạng \1", slot="numbers"),
]


class TemplateEngine:
    """Applies template rules against text, replacing matched patterns."""

    def __init__(self, rules: List[TemplateRule] | None = None):
        self.rules = rules or DEFAULT_RULES
        self._compiled: Dict[str, re.Pattern] = {}
        self._compile_all()

    def _compile_all(self) -> None:
        """Pre-compile regex patterns for all rules."""
        for rule in self.rules:
            pattern = rule.src
            if pattern not in self._compiled:
                self._compiled[pattern] = re.compile(pattern)

    def apply(
        self,
        text: str,
        lexicon: Lexicon | None = None,
        protected_spans: List[tuple[int, int]] | None = None,
    ) -> str:
        """Apply template rules to text.

        Args:
            text: Source text to process
            lexicon: Optional Lexicon for slot dictionary lookups
            protected_spans: Optional list of (start, end) spans to skip

        Returns:
            Processed text with template rules applied
        """
        protected = set()
        if protected_spans:
            for start, end in protected_spans:
                for pos in range(start, end):
                    protected.add(pos)

        result = text
        for rule in self.rules:
            compiled = self._compiled[rule.src]
            offset = 0
            for match in compiled.finditer(result):
                start = match.start()
                end = match.end()

                # Check if match overlaps a protected span
                skip = False
                for pos in range(start, end):
                    if pos in protected:
                        skip = True
                        break
                if skip:
                    continue

                slot_value = match.group(1) if match.lastindex else match.group(0)
                replacement = rule.dst

                # If lexicon provided and slot references names/phrases, do lookup
                if lexicon and rule.slot in ("names", "all"):
                    if slot_value in lexicon.name_dict:
                        replacement = replacement.replace(
                            "\\1",
                            lexicon.name_dict[slot_value]
                        )
                elif lexicon and rule.slot in ("phrases", "all"):
                    if slot_value in lexicon.phrase_dict:
                        replacement = replacement.replace(
                            "\\1",
                            lexicon.phrase_dict[slot_value]
                        )

                replacement = replacement.replace("\\1", slot_value)
                result = result[:start + offset] + replacement + result[end + offset:]
                offset += len(replacement) - (end - start)

        return result


def load_default_template_rules() -> TemplateEngine:
    """Return a TemplateEngine with default rules pre-loaded."""
    return TemplateEngine(DEFAULT_RULES)
