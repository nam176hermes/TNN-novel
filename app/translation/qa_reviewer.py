from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Optional

import requests
from rich.console import Console

from app.config import settings
from app.translation.ollama_client import TranslationError, call_openai_compatible_chat, _record_provider_usage_from_response
from app.translation.pronoun_memory import find_pronoun_issues, render_pronoun_memory
from app.translation.style_rule_engine import apply_hard_style_qa

console = Console()

QA_PROMPT = """Compare the Chinese source and Vietnamese translation.

Return JSON only.

Check:
1. Missing source paragraphs.
2. Source paragraphs that were summarized instead of translated.
3. Added plot details not present in source.
4. Wrong names, sects, kinship terms, places, money units, chapter titles.
5. Machine-translation phrases or unnatural Vietnamese.
6. Modern vocabulary where cổ trang wording is better.
7. Untranslated Chinese fragments.
8. Modern pronouns tôi/bạn/anh/em in cổ trang dialogue where ta/ngươi/huynh/tỷ/đệ/muội/tiền bối is expected.

{pronoun_memory}

Scoring:
- fidelity_score: 0-10
- style_score: 0-10
- glossary_score: 0-10
- audiobook_score: 0-10

Use this JSON structure:
{
  "fidelity_score": 0,
  "style_score": 0,
  "glossary_score": 0,
  "audiobook_score": 0,
  "critical_issues": [],
  "paragraph_alignment_issues": [],
  "term_issues": [],
  "style_rewrites": [],
  "verdict": "PASS or FAIL"
}

Automatic fail conditions:
- Any complete source paragraph is missing.
- More than one paragraph is compressed into a summary.
- A major named entity is mistranslated.

Source (Chinese):
{source}

Translation (Vietnamese):
{translation}"""


def _apply_deterministic_pronoun_qa(report: dict, translated_text: str) -> dict:
    pronoun_issues = find_pronoun_issues(translated_text)
    if not pronoun_issues:
        return report

    existing_issues = list(report.get("issues", []))
    existing_issues.extend(pronoun_issues)
    report["issues"] = existing_issues
    return report


def _apply_deterministic_qa(report: dict, source_text: str, translated_text: str, style_profile_id=None) -> dict:
    if style_profile_id is not None and style_profile_id not in {"tien_hiep", "kiem_hiep", "co_trang", "huyen_huyen"}:
        return report
    report = apply_hard_style_qa(report, source_text, translated_text)
    return _apply_deterministic_pronoun_qa(report, translated_text)


def run_qa_check(
    source_text: str,
    translated_text: str,
    model: Optional[str] = None,
    host: Optional[str] = None,
    api_key: Optional[str] = None,
    db_path: Optional[Path] = None,
    provider_id: Optional[str] = None,
    task_type: str = "qa",
    job_id: str = "",
    chapter_id: Optional[int] = None,
    style_profile_id: Optional[str] = None,
) -> dict:
    """Run QA check on a translation. Returns dict with fidelity/style/glossary scores."""
    model = model or settings.ollama_model
    host = host or settings.ollama_host
    import os
    resolved_api_key = api_key if api_key is not None else settings.ollama_api_key or os.environ.get("NINEROUTER_API_KEY", "")

    prompt = (
        QA_PROMPT.replace("{source}", source_text)
        .replace("{translation}", translated_text)
        .replace("{pronoun_memory}", render_pronoun_memory())
    )

    if style_profile_id is not None:
        prompt = prompt.replace("6. Modern vocabulary where cổ trang wording is better.", "6. Follow the selected style; do not impose historical wording on modern settings.")
        prompt = prompt.replace("8. Modern pronouns tôi/bạn/anh/em in cổ trang dialogue where ta/ngươi/huynh/tỷ/đệ/muội/tiền bối is expected.", "8. Preserve pronoun referents and relationships according to the source and selected style.")
        prompt = f"Selected style: {style_profile_id}\n" + prompt
    try:
        result = call_openai_compatible_chat(
            prompt=prompt,
            base_url=host,
            model=model,
            api_key=resolved_api_key,
            temperature=0.1,
            timeout=120,
        )
        if db_path is not None:
            _record_provider_usage_from_response(
                db_path=db_path,
                provider_id=provider_id,
                model=model,
                task_type=task_type,
                usage=result.get("usage", {}),
                job_id=job_id,
                chapter_id=chapter_id,
            )
        raw_output = result.get("text", "").strip()

        json_match = re.search(r'\{[\s\S]*\}', raw_output)
        if not json_match:
            raise ValueError("QA response is not JSON")
        report = json.loads(json_match.group())
        if not isinstance(report, dict) or report.get("verdict") not in {"PASS", "FAIL", "WARN", "WARNING"}:
            raise ValueError("QA verdict is invalid")
        scores = []
        for key in ("fidelity_score", "style_score", "glossary_score", "audiobook_score"):
            value = report.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10:
                raise ValueError("QA score is invalid")
            scores.append(value)
        issues = []
        for key in ("critical_issues", "paragraph_alignment_issues", "term_issues", "style_rewrites"):
            items = report.get(key, [])
            if not isinstance(items, list):
                raise ValueError("QA issues are invalid")
            issues.extend(item if isinstance(item, dict) else {"type": key, "message": str(item)} for item in items)
        report.update(quality_score=round(sum(scores) / 4, 1), issues=issues, qa_complete=True)
        if report.get("critical_issues") or report.get("paragraph_alignment_issues"):
            report["verdict"] = "FAIL"
        return _apply_deterministic_qa(report, source_text, translated_text, style_profile_id)
    except (requests.RequestException, TranslationError, ValueError, TypeError) as exc:
        issue_type = "qa_request_failed" if isinstance(exc, (requests.RequestException, TranslationError)) else "qa_parse_error"
        return _apply_deterministic_qa({
            "fidelity_score": 0, "style_score": 0, "glossary_score": 0, "audiobook_score": 0,
            "quality_score": 0, "verdict": "WARNING", "qa_complete": False,
            "issues": [{"type": issue_type, "severity": "low", "message": "Semantic QA did not complete"}],
        }, source_text, translated_text, style_profile_id)


def format_qa_report(report: dict) -> str:
    """Format QA report for console display."""
    scores = [
        ("Fidelity", report.get("fidelity_score", 0)),
        ("Style", report.get("style_score", 0)),
        ("Glossary", report.get("glossary_score", 0)),
        ("Audiobook", report.get("audiobook_score", 0)),
    ]
    verdict = report.get("verdict", "UNKNOWN")
    overall = report.get("quality_score", 0)

    color = "green" if overall >= 8.0 else "yellow" if overall >= 6.0 else "red"
    lines = [f"QA Score: [{color}]{overall:.1f}/10[/{color}] | Verdict: [{color}]{verdict}[/{color}]"]
    for name, score in scores:
        sc = "green" if score >= 8 else "yellow" if score >= 6 else "red"
        lines.append(f"  [{sc}]{name}: {score}/10[/{sc}]")

    issues = report.get("issues", [])
    if issues:
        lines.append(f"Issues found: {len(issues)}")
        for i, issue in enumerate(issues[:5], 1):
            lines.append(f"  {i}. {issue.get('type', 'unknown')}: {issue.get('suggested_fix', '')[:80]}")

    return "\n".join(lines)
