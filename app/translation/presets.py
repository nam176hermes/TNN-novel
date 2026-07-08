from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationPreset:
    id: str
    label: str
    description: str
    providers: dict[str, str]
    chunk_size: int | None = None
    polish_enabled: bool = True
    qa_enabled: bool = True
    rewrite_failed: bool = False


TRANSLATION_PRESETS: dict[str, TranslationPreset] = {
    "fast_draft": TranslationPreset(
        id="fast_draft",
        label="Nhanh",
        description="Dịch nháp nhanh bằng một model, chỉ chạy rule engine hậu kỳ local.",
        providers={"translate": "deepseek"},
        chunk_size=3500,
        polish_enabled=False,
        qa_enabled=False,
        rewrite_failed=False,
    ),
    "cheapest": TranslationPreset(
        id="cheapest",
        label="Rẻ nhất",
        description="Dịch, polish và QA bằng các model rẻ/free.",
        providers={"translate": "gemini", "polish": "gemini", "qa": "deepseek", "rewrite": "gemini"},
        rewrite_failed=False,
    ),
    "balanced": TranslationPreset(
        id="balanced",
        label="Cân bằng",
        description="Dịch bằng model rẻ, polish bằng model ổn định hơn, QA riêng.",
        providers={"translate": "deepseek", "polish": "gemini", "qa": "deepseek", "rewrite": "gemini"},
        rewrite_failed=False,
    ),
    "quality_high": TranslationPreset(
        id="quality_high",
        label="Chất lượng cao",
        description="Dịch, polish, QA, rồi rewrite khi QA phát hiện lỗi.",
        providers={"translate": "deepseek", "polish": "gemini", "qa": "deepseek", "rewrite": "gemini"},
        rewrite_failed=True,
    ),
}


def get_translation_preset(preset_id: str | None) -> TranslationPreset:
    resolved = preset_id or "balanced"
    try:
        return TRANSLATION_PRESETS[resolved]
    except KeyError as exc:
        raise ValueError(f"Unknown translation preset: {resolved}") from exc


def list_translation_presets() -> list[dict]:
    return [
        {
            "id": preset.id,
            "label": preset.label,
            "description": preset.description,
            "chunk_size": preset.chunk_size,
            "polish_enabled": preset.polish_enabled,
            "qa_enabled": preset.qa_enabled,
            "rewrite_failed": preset.rewrite_failed,
        }
        for preset in TRANSLATION_PRESETS.values()
    ]
