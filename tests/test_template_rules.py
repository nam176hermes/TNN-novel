from __future__ import annotations

from app.translation.template_rules import TemplateEngine, TemplateRule


def test_template_rule_without_capture_group_replaces_literal_match() -> None:
    engine = TemplateEngine([TemplateRule(src=r"完", dst="Hết", slot="all")])

    assert engine.apply("完") == "Hết"
