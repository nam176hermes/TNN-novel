from __future__ import annotations

import requests

from app.translation import qa_reviewer
from app.translation.qa_reviewer import format_qa_report


def test_format_qa_report_high_score_green():
    report = {
        "quality_score": 9.0,
        "verdict": "PASS",
        "fidelity_score": 9,
        "style_score": 9,
        "glossary_score": 9,
        "audiobook_score": 9,
        "issues": [],
    }
    output = format_qa_report(report)
    # Check that the score is formatted and color is green (>=8.0)
    assert "QA Score: [green]9.0/10[/green]" in output
    assert "Verdict: [green]PASS[/green]" in output
    # Each dimension should be green
    assert "[green]Fidelity: 9/10[/green]" in output
    assert "[green]Style: 9/10[/green]" in output
    assert "[green]Glossary: 9/10[/green]" in output
    assert "[green]Audiobook: 9/10[/green]" in output
    # No issues section
    assert "Issues found:" not in output


def test_format_qa_report_low_score_red():
    report = {
        "quality_score": 4.0,
        "verdict": "FAIL",
        "fidelity_score": 4,
        "style_score": 4,
        "glossary_score": 4,
        "audiobook_score": 4,
        "issues": [{"type": "test_issue", "suggested_fix": "Fix this"}],
    }
    output = format_qa_report(report)
    assert "QA Score: [red]4.0/10[/red]" in output
    assert "Verdict: [red]FAIL[/red]" in output
    assert "[red]Fidelity: 4/10[/red]" in output
    assert "[red]Style: 4/10[/red]" in output
    assert "[red]Glossary: 4/10[/red]" in output
    assert "[red]Audiobook: 4/10[/red]" in output
    # Issues should be included
    assert "Issues found: 1" in output
    assert "1. test_issue: Fix this" in output


def test_format_qa_report_middle_score_yellow():
    report = {
        "quality_score": 6.5,
        "verdict": "PASS",
        "fidelity_score": 7,
        "style_score": 6,
        "glossary_score": 7,
        "audiobook_score": 6,
        "issues": [],
    }
    output = format_qa_report(report)
    # Overall 6.5 -> yellow (between 6.0 and 8.0)
    assert "QA Score: [yellow]6.5/10[/yellow]" in output
    assert "Verdict: [yellow]PASS[/yellow]" in output
    # Fidelity 7 -> green? Wait: fidelity_score 7 >=8? No, 7 is between 6 and 8 -> yellow
    # Actually the function: sc = "green" if score >= 8 else "yellow" if score >= 6 else "red"
    # So 7 -> yellow, 6 -> yellow, 5 -> red
    assert "[yellow]Fidelity: 7/10[/yellow]" in output
    assert "[yellow]Style: 6/10[/yellow]" in output
    assert "[yellow]Glossary: 7/10[/yellow]" in output
    assert "[yellow]Audiobook: 6/10[/yellow]" in output


def test_run_qa_check_records_provider_usage(monkeypatch, tmp_path) -> None:
    from app.database.db import get_usage_summary, init_db

    db_path = tmp_path / "pipeline.db"
    init_db(db_path)

    def fake_chat(**kwargs):
        return {
            "text": """
            {
              "fidelity_score": 9,
              "style_score": 8,
              "glossary_score": 8,
              "audiobook_score": 9,
              "critical_issues": [],
              "paragraph_alignment_issues": [],
              "term_issues": [],
              "style_rewrites": [],
              "verdict": "PASS"
            }
            """,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="原文",
        translated_text="Bản dịch",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
        db_path=db_path,
        provider_id="gemini",
        chapter_id=3,
    )

    assert report["quality_score"] == 8.5
    assert get_usage_summary(db_path) == {
        "total_prompt_tokens": 1000,
        "total_completion_tokens": 500,
        "total_tokens": 1500,
        "total_estimated_cost_usd": 0.0003,
    }


def test_run_qa_check_flags_modern_pronouns_in_classical_context(monkeypatch) -> None:
    def fake_chat(**kwargs):
        return {
            "text": """
            {
              "fidelity_score": 9,
              "style_score": 9,
              "glossary_score": 9,
              "audiobook_score": 9,
              "critical_issues": [],
              "paragraph_alignment_issues": [],
              "term_issues": [],
              "style_rewrites": [],
              "verdict": "PASS"
            }
            """,
            "usage": {},
        }

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="陆哥，这几日多亏你照顾。",
        translated_text="Lục ca, mấy ngày nay tôi đã phiền anh chăm sóc.",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
    )

    pronoun_issues = [issue for issue in report["issues"] if issue.get("type") == "pronoun_modern"]
    assert pronoun_issues
    assert report["verdict"] == "FAIL"
    assert report["style_score"] <= 6


def test_run_qa_check_flags_third_person_after_direct_vocative(monkeypatch) -> None:
    def fake_chat(**kwargs):
        return {
            "text": """
            {
              "fidelity_score": 9,
              "style_score": 9,
              "glossary_score": 9,
              "audiobook_score": 9,
              "critical_issues": [],
              "paragraph_alignment_issues": [],
              "term_issues": [],
              "style_rewrites": [],
              "verdict": "PASS"
            }
            """,
            "usage": {},
        }

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="陆哥，这几日多亏你照顾。",
        translated_text="Lục ca, mấy ngày nay đã phiền hắn chăm sóc nhiều rồi, ta còn chưa biết báo đáp thế nào.",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
    )

    direct_address_issues = [
        issue for issue in report["issues"] if issue.get("type") == "pronoun_direct_address"
    ]
    assert direct_address_issues
    assert "Lục ca" in direct_address_issues[0]["segment"]
    assert report["verdict"] == "FAIL"


def test_run_qa_check_flags_modern_pronouns_when_provider_request_fails(monkeypatch) -> None:
    def fake_chat(**kwargs):
        raise requests.RequestException("provider offline")

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="陆哥，这几日多亏你照顾。",
        translated_text="Lục ca, mấy ngày nay tôi đã phiền anh chăm sóc.",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
    )

    issue_types = [issue.get("type") for issue in report["issues"]]
    assert "qa_request_failed" in issue_types
    assert "pronoun_modern" in issue_types
    assert report["verdict"] == "FAIL"


def test_run_qa_check_hard_fails_system_and_forbidden_translation_errors(monkeypatch) -> None:
    def fake_chat(**kwargs):
        return {
            "text": """
            {
              "fidelity_score": 10,
              "style_score": 10,
              "glossary_score": 10,
              "audiobook_score": 10,
              "critical_issues": [],
              "paragraph_alignment_issues": [],
              "term_issues": [],
              "style_rewrites": [],
              "verdict": "PASS"
            }
            """,
            "usage": {},
        }

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="叮！检测到宿主完成隐藏任务，奖励积分一万点，是否领取？",
        translated_text="Đinh! Phát hiện chủ nhà hoàn thành ẩn vụ, ban thưởng một vạn tích phân, có nhận hay không?",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
    )

    issue_types = {issue.get("type") for issue in report["issues"]}
    assert "forbidden_translation" in issue_types
    assert "system_term_error" in issue_types
    assert "system_ui_format" in issue_types
    assert report["verdict"] == "FAIL"
    assert report["style_score"] <= 6
    assert report["glossary_score"] <= 6


def test_run_qa_check_flags_split_dinh_prefix_as_bad_system_format(monkeypatch) -> None:
    def fake_chat(**kwargs):
        return {
            "text": """
            {
              "fidelity_score": 10,
              "style_score": 10,
              "glossary_score": 10,
              "audiobook_score": 10,
              "critical_issues": [],
              "paragraph_alignment_issues": [],
              "term_issues": [],
              "style_rewrites": [],
              "verdict": "PASS"
            }
            """,
            "usage": {},
        }

    monkeypatch.setattr(qa_reviewer, "call_openai_compatible_chat", fake_chat)

    report = qa_reviewer.run_qa_check(
        source_text="叮！检测到宿主完成隐藏任务，奖励积分一万点，是否领取？",
        translated_text="[Đinh!] Phát hiện ký chủ hoàn thành nhiệm vụ ẩn, ban thưởng một vạn điểm tích lũy, có lĩnh không?",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
    )

    assert any(issue.get("type") == "system_ui_format" for issue in report["issues"])
    assert report["verdict"] == "FAIL"
