from __future__ import annotations

from app.translation.presets import get_translation_preset, list_translation_presets


def test_fast_draft_preset_only_enables_translate_stage() -> None:
    preset = get_translation_preset("fast_draft")

    assert preset.id == "fast_draft"
    assert preset.providers["translate"] == "deepseek"
    assert preset.chunk_size == 3500
    assert preset.polish_enabled is False
    assert preset.qa_enabled is False
    assert preset.rewrite_failed is False


def test_list_translation_presets_includes_fast_draft_for_ui_metadata() -> None:
    presets = list_translation_presets()

    fast_draft = next(item for item in presets if item["id"] == "fast_draft")
    assert fast_draft["label"] == "Nhanh"
    assert fast_draft["chunk_size"] == 3500
    assert fast_draft["polish_enabled"] is False
    assert fast_draft["qa_enabled"] is False
