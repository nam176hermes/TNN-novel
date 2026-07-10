from __future__ import annotations

import re

from app.translation.styleguide_config import (
    get_forbidden_translation_rules,
    get_literary_phrase_pairs,
    get_locked_terms,
)


SYSTEM_TERM_FIXES = {
    "ẩn vụ": "nhiệm vụ ẩn",
    "Ẩn vụ": "Nhiệm vụ ẩn",
}


def _target_by_source() -> dict[str, str]:
    return {
        str(term.get("source") or ""): str(term.get("target") or "")
        for term in get_locked_terms()
        if str(term.get("source") or "") and str(term.get("target") or "")
    }


def normalize_forbidden_translation_terms(text: str) -> str:
    target_by_source = _target_by_source()
    for source, wrong_values in get_forbidden_translation_rules().items():
        target = target_by_source.get(source, "")
        if not target:
            continue
        for wrong in wrong_values:
            if not wrong:
                continue
            text = text.replace(wrong, target)
            text = text.replace(wrong[:1].upper() + wrong[1:], target[:1].upper() + target[1:])
    return text


def normalize_system_terms(text: str) -> str:
    for wrong, correct in SYSTEM_TERM_FIXES.items():
        text = text.replace(wrong, correct)
    return text


def _strip_sentence_punctuation(value: str) -> str:
    return value.strip().strip(" .,;:!?。！？；：，")


def _sentence(value: str) -> str:
    value = _strip_sentence_punctuation(value)
    if not value:
        return ""
    return value if value.endswith(("?", "!", ".")) else f"{value}."


def _question(value: str) -> str:
    value = _strip_sentence_punctuation(value)
    if not value:
        return ""
    return value if value.endswith("?") else f"{value}?"


def _normalize_receive_question(value: str) -> str:
    lowered = value.lower()
    if "có nhận" not in lowered and "có lĩnh" not in lowered:
        return value
    return "Có nhận không?"


def _format_system_line(line: str) -> str:
    original = line.strip()
    if not original:
        return line

    bracketed = original.startswith("[") and original.endswith("]")
    inner = original[1:-1].strip() if bracketed else original
    inner = re.sub(r"^\[\s*(Đinh\s*!)\s*\]\s*", r"\1 ", inner, flags=re.IGNORECASE)
    if not re.match(r"(?i)^đinh\s*!", inner):
        return line

    inner = normalize_system_terms(normalize_forbidden_translation_terms(inner))
    reward_match = re.search(
        r"(?:,\s*)?(?:ban thưởng|phần thưởng)\s*[:：]?\s*(?P<reward>.*?)(?:,\s*(?P<question>có (?:nhận|lĩnh).*)|$)",
        inner,
        flags=re.IGNORECASE,
    )
    if not reward_match:
        return f"[{_sentence(inner)}]"

    body = _sentence(inner[: reward_match.start()])
    reward = _sentence(reward_match.group("reward") or "")
    question = _normalize_receive_question(reward_match.group("question") or "")

    lines = []
    if body:
        lines.append(f"[{body}]")
    if reward:
        lines.append(f"[Phần thưởng: {reward[:1].lower() + reward[1:]}]")
    if question:
        lines.append(f"[{_question(question)}]")
    return "\n".join(lines) if lines else f"[{_sentence(inner)}]"


def normalize_system_notifications(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    return "\n".join(_format_system_line(line) for line in lines)


def normalize_style_rule_text(text: str) -> str:
    text = normalize_forbidden_translation_terms(text)
    text = normalize_system_terms(text)
    text = normalize_system_notifications(text)
    return text


def find_hard_style_issues(source_text: str, translated_text: str) -> list[dict]:
    issues: list[dict] = []
    lower_translation = translated_text.lower()
    target_by_source = _target_by_source()

    for source, wrong_values in get_forbidden_translation_rules().items():
        expected = target_by_source.get(source, "")
        for wrong in wrong_values:
            if wrong and wrong.lower() in lower_translation:
                issues.append(
                    {
                        "type": "forbidden_translation",
                        "severity": "high",
                        "source_term": source,
                        "bad_text": wrong,
                        "expected": expected,
                        "message": f"'{wrong}' should be replaced with '{expected}'.",
                    }
                )

    if re.search(r"\bẩn vụ\b", lower_translation, flags=re.IGNORECASE):
        issues.append(
            {
                "type": "system_term_error",
                "severity": "high",
                "bad_text": "ẩn vụ",
                "expected": "nhiệm vụ ẩn",
                "message": "System-task phrase should use 'nhiệm vụ ẩn', not 'ẩn vụ'.",
            }
        )

    has_system_source = "叮" in source_text or "系统" in source_text
    if has_system_source or "đinh!" in lower_translation:
        if (
            re.search(r"(?m)^\s*Đinh\s*!", translated_text)
            or re.search(r"(?<!\[)Đinh\s*!", translated_text)
            or re.search(r"(?m)^\s*\[\s*Đinh\s*!\s*\]\s+\S", translated_text)
        ):
            issues.append(
                {
                    "type": "system_ui_format",
                    "severity": "medium",
                    "bad_text": "Đinh!",
                    "expected": "[Đinh! ...]",
                    "message": "System notifications should use square-bracket UI lines.",
                }
            )

    for chinese, expected in get_literary_phrase_pairs():
        if chinese and chinese in translated_text:
            issues.append(
                {
                    "type": "untranslated_literary_phrase",
                    "severity": "high",
                    "source_term": chinese,
                    "bad_text": chinese,
                    "expected": expected,
                    "message": "Chinese literary phrase leaked into Vietnamese translation.",
                }
            )

    return issues


def recompute_quality_score(report: dict) -> None:
    scores = [
        float(report.get("fidelity_score", 0) or 0),
        float(report.get("style_score", 0) or 0),
        float(report.get("glossary_score", 0) or 0),
        float(report.get("audiobook_score", 0) or 0),
    ]
    report["quality_score"] = round(sum(scores) / 4, 1)


def apply_hard_style_qa(report: dict, source_text: str, translated_text: str) -> dict:
    hard_issues = find_hard_style_issues(source_text, translated_text)
    if not hard_issues:
        return report

    existing = list(report.get("issues", []))
    existing.extend(hard_issues)
    report["issues"] = existing

    issue_types = {issue.get("type") for issue in hard_issues}
    if issue_types & {"system_ui_format", "system_term_error", "untranslated_literary_phrase"}:
        report["style_score"] = min(float(report.get("style_score", 0) or 0), 6)
    if issue_types & {"forbidden_translation", "system_term_error", "untranslated_literary_phrase"}:
        report["glossary_score"] = min(float(report.get("glossary_score", 0) or 0), 6)
    report["verdict"] = "FAIL"
    recompute_quality_score(report)
    return report
