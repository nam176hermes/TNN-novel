from __future__ import annotations

from app.translation.literary_style import matching_literary_phrase_pairs, render_literary_phrase_guide
from app.translation.styleguide_config import (
    get_forbidden_translation_rules,
    get_locked_terms,
    get_styleguide_config,
)


def test_styleguide_config_loads_locked_terms_and_forbidden_rules() -> None:
    config = get_styleguide_config()
    locked_terms = get_locked_terms()
    forbidden = get_forbidden_translation_rules()

    assert config["metadata"]["source_document"] == "cn_vi_webnovel_translation_styleguide.md"
    assert any(term["source"] == "宿主" and term["target"] == "ký chủ" for term in locked_terms)
    assert any(term["source"] == "灵气" and term["target"] == "linh khí" for term in locked_terms)
    assert forbidden["宿主"] == ["chủ nhà"]
    assert forbidden["积分"] == ["tích phân"]


def test_literary_phrase_guide_uses_styleguide_config_pairs() -> None:
    source = "老者低声道：天地不仁，以万物为刍狗。"

    assert matching_literary_phrase_pairs(source) == [
        ("天地不仁，以万物为刍狗", "trời đất bất nhân, xem vạn vật như chó rơm")
    ]
    rendered = render_literary_phrase_guide(source)
    assert "天地不仁，以万物为刍狗 -> trời đất bất nhân, xem vạn vật như chó rơm" in rendered
