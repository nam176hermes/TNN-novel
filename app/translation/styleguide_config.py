from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any


STYLEGUIDE_CONFIG_PATH = Path(__file__).with_name("styleguide_config.json")


@lru_cache(maxsize=1)
def get_styleguide_config() -> dict[str, Any]:
    with STYLEGUIDE_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    if not isinstance(config, dict):
        raise ValueError("Styleguide config root must be an object")
    return config


def get_literary_style_guide_lines() -> list[str]:
    lines = get_styleguide_config().get("literary_style_guide", [])
    return [str(line).strip() for line in lines if str(line).strip()]


def get_literary_phrase_pairs() -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in get_styleguide_config().get("literary_phrase_pairs", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if source and target:
            pairs.append((source, target))
    return tuple(pairs)


def get_locked_terms() -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for item in get_styleguide_config().get("locked_terms", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if source and target:
            terms.append(item)
    return terms


def get_forbidden_translation_rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    raw_rules = get_styleguide_config().get("forbidden_translation_rules", {})
    if not isinstance(raw_rules, dict):
        return rules
    for source, wrong_values in raw_rules.items():
        source_term = str(source).strip()
        if not source_term:
            continue
        if isinstance(wrong_values, list):
            values = [str(value).strip() for value in wrong_values if str(value).strip()]
        else:
            values = [str(wrong_values).strip()] if str(wrong_values).strip() else []
        if values:
            rules[source_term] = values
    return rules


def get_genre_presets() -> dict[str, dict[str, Any]]:
    presets = get_styleguide_config().get("genre_presets", {})
    if not isinstance(presets, dict):
        return {}
    return {str(key): value for key, value in presets.items() if isinstance(value, dict)}
