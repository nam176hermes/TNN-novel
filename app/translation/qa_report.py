"""Combine independent QA evidence without turning incomplete checks into PASS."""
from __future__ import annotations


def merge_qa_report(rule_based=None, semantic=None, coverage=None, provenance=None) -> dict:
    rule = rule_based or {}
    sem = semantic or {}
    coverage = coverage or {"complete": False, "required": True}
    failed = rule.get("overall_status", rule.get("verdict")) == "FAIL" or sem.get("verdict") == "FAIL"
    complete = bool(sem) and coverage.get("complete", False) and sem.get("qa_complete", True) and coverage.get("pipeline_complete", True)
    warning = rule.get("overall_status") == "WARNING" or sem.get("verdict") in {"WARN", "WARNING"}
    quality_status = "needs_review" if failed or (complete and warning) else "pass" if complete else (
        "unreviewed" if not coverage.get("required", True) else "partial"
    )
    verdict = "FAIL" if failed else "WARNING" if warning or not complete else "PASS"
    result = {**rule, "report_version": 1, "rule_based": rule, "semantic": sem or None,
              "coverage": coverage, "provenance": provenance or {},
              "quality_status": quality_status, "verdict": verdict, "overall_status": verdict}
    for name in ("quality_score", "fidelity_score", "style_score", "glossary_score", "audiobook_score"):
        # Text rules cannot judge speech quality; their historical zero is not audio evidence.
        parts = (sem,) if name == "audiobook_score" else (rule, sem)
        values = [float(part[name]) for part in parts if name in part and part[name] is not None]
        result[name] = min(values) if values else 0
    result["issues"] = [*rule.get("issues", []), *sem.get("issues", [])]
    return result
