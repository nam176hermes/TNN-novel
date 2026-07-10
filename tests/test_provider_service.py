from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database.db import (
    get_provider_defaults,
    init_db,
    list_model_providers,
    put_model_provider,
    record_provider_usage,
    seed_default_model_providers,
    get_usage_summary,
)


def test_model_provider_crud_masks_secrets(temp_db_path: Path, monkeypatch) -> None:
    init_db(temp_db_path)
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")

    provider_id = put_model_provider(
        temp_db_path,
        provider_id="gemini",
        label="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash-lite",
        api_key_env="GEMINI_API_KEY",
        cost_input_per_1m=0.10,
        cost_output_per_1m=0.40,
        enabled=1,
    )
    providers = list_model_providers(temp_db_path)
    gemini = next(item for item in providers if item["id"] == "gemini")

    assert provider_id == "gemini"
    assert gemini["api_key_env"] == "GEMINI_API_KEY"
    assert gemini["api_key_set"] is True
    assert "secret-value" not in str(gemini)


def test_fresh_db_seeds_default_model_providers(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    providers = list_model_providers(temp_db_path)

    assert {provider["id"] for provider in providers} >= {
        "gemini",
        "deepseek",
        "openrouter",
        "ollama",
    }


def test_provider_defaults_include_all_default_tasks(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    defaults = get_provider_defaults(temp_db_path)

    assert defaults["translate"] == "gemini"
    assert defaults["qa"] == "deepseek"
    assert defaults["polish"] == "gemini"
    assert defaults["retranslate"] == "gemini"


def test_empty_api_key_env_reports_not_set(temp_db_path: Path, monkeypatch) -> None:
    init_db(temp_db_path)
    monkeypatch.setenv("GEMINI_API_KEY", "   ")

    providers = list_model_providers(temp_db_path)
    gemini = next(item for item in providers if item["id"] == "gemini")

    assert gemini["api_key_set"] is False


def test_partial_legacy_provider_table_migrates_before_seeding(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-providers.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            base_url TEXT NOT NULL,
            model TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    providers = list_model_providers(db_path)
    gemini = next(item for item in providers if item["id"] == "gemini")

    assert gemini["api_key_env"] == "GEMINI_API_KEY"
    assert gemini["cost_input_per_1m"] == 0.10
    assert gemini["cost_output_per_1m"] == 0.40


def test_partial_legacy_provider_rows_are_backfilled(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-provider-rows.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            base_url TEXT NOT NULL,
            model TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers (id, label, base_url, model)
        VALUES (?, ?, ?, ?)
        """,
        (
            "gemini",
            "Gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "gemini-2.5-flash-lite",
        ),
    )
    conn.execute(
        """
        CREATE TABLE provider_defaults (
            task_type TEXT PRIMARY KEY,
            provider_id TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        "INSERT INTO provider_defaults (task_type, provider_id) VALUES (?, ?)",
        ("translate", ""),
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    providers = list_model_providers(db_path)
    defaults = get_provider_defaults(db_path)
    gemini = next(item for item in providers if item["id"] == "gemini")

    assert gemini["api_key_env"] == "GEMINI_API_KEY"
    assert gemini["cost_input_per_1m"] == 0.10
    assert gemini["cost_output_per_1m"] == 0.40
    assert defaults["translate"] == "gemini"


def test_legacy_id_only_default_provider_backfills_blank_core_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-id-only-provider.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT DEFAULT '',
            base_url TEXT DEFAULT '',
            model TEXT DEFAULT ''
        )
        """
    )
    conn.execute("INSERT INTO model_providers (id) VALUES (?)", ("openrouter",))
    conn.commit()
    conn.close()

    init_db(db_path)
    providers = list_model_providers(db_path)
    openrouter = next(item for item in providers if item["id"] == "openrouter")

    assert openrouter["label"] == "OpenRouter"
    assert openrouter["base_url"] == "https://openrouter.ai/api/v1"
    assert openrouter["model"] == "openrouter/free"
    assert openrouter["api_key_env"] == "OPENROUTER_API_KEY"
    assert openrouter["notes"] == "Free router, model may vary."


def test_listing_complete_default_provider_does_not_touch_updated_at(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    expected_updated_at = "2000-01-01 00:00:00"
    with sqlite3.connect(str(temp_db_path)) as conn:
        conn.execute(
            "UPDATE model_providers SET updated_at = ? WHERE id = ?",
            (expected_updated_at, "gemini"),
        )
        conn.commit()

    list_model_providers(temp_db_path)

    with sqlite3.connect(str(temp_db_path)) as conn:
        actual_updated_at = conn.execute(
            "SELECT updated_at FROM model_providers WHERE id = ?",
            ("gemini",),
        ).fetchone()[0]

    assert actual_updated_at == expected_updated_at


def test_blank_optional_default_provider_fields_remain_blank_after_reads_and_seed(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="gemini",
        label="Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash-lite",
        api_key_env="",
        notes="",
    )

    listed_gemini = next(item for item in list_model_providers(temp_db_path) if item["id"] == "gemini")
    with sqlite3.connect(str(temp_db_path)) as conn:
        seed_default_model_providers(conn)
        conn.commit()
        stored_gemini = conn.execute(
            "SELECT api_key_env, notes FROM model_providers WHERE id = ?",
            ("gemini",),
        ).fetchone()

    assert listed_gemini["api_key_env"] == ""
    assert listed_gemini["notes"] == ""
    assert stored_gemini == ("", "")


def test_blank_core_default_provider_row_gets_backfilled(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-blank-core-provider.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT DEFAULT '',
            base_url TEXT DEFAULT '',
            model TEXT DEFAULT '',
            api_key_env TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers (id, label, base_url, model, api_key_env, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("deepseek", "", "", "", "", "", "2000-01-01 00:00:00"),
    )
    conn.commit()
    conn.close()

    providers = list_model_providers(db_path)
    deepseek = next(item for item in providers if item["id"] == "deepseek")

    assert deepseek["label"] == "DeepSeek"
    assert deepseek["base_url"] == "https://api.deepseek.com/v1"
    assert deepseek["model"] == "deepseek-v4-flash"
    assert deepseek["api_key_env"] == "DEEPSEEK_API_KEY"
    assert deepseek["notes"] == "Default QA provider."
    assert deepseek["updated_at"] != "2000-01-01 00:00:00"


def test_custom_legacy_provider_keeps_safe_defaults_for_added_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "custom-legacy-provider.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            base_url TEXT NOT NULL,
            model TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers (id, label, base_url, model)
        VALUES (?, ?, ?, ?)
        """,
        ("custom", "Custom", "https://custom.example/v1", "custom-model"),
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    providers = list_model_providers(db_path)
    custom = next(item for item in providers if item["id"] == "custom")

    assert custom["temperature"] == 0.3
    assert custom["supports_streaming"] == 0
    assert custom["supports_batch"] == 0
    assert custom["cost_input_per_1m"] == 0
    assert custom["cost_output_per_1m"] == 0


def test_seeding_preserves_operator_zero_values_for_default_provider(tmp_path: Path) -> None:
    db_path = tmp_path / "operator-zero-values.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE model_providers (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            base_url TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key_env TEXT DEFAULT '',
            temperature REAL DEFAULT 0.3,
            timeout_seconds INTEGER DEFAULT 180,
            supports_streaming INTEGER DEFAULT 0,
            supports_batch INTEGER DEFAULT 0,
            cost_input_per_1m REAL DEFAULT 0,
            cost_output_per_1m REAL DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            notes TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO model_providers
            (id, label, base_url, model, api_key_env, temperature, timeout_seconds,
             supports_streaming, supports_batch, cost_input_per_1m, cost_output_per_1m,
             enabled, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "gemini",
            "Operator Gemini",
            "https://operator.example/v1",
            "operator-model",
            "OPERATOR_KEY",
            0,
            90,
            0,
            0,
            0,
            0,
            1,
            "operator custom notes",
        ),
    )
    conn.execute(
        """
        CREATE TABLE provider_defaults (
            task_type TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO provider_defaults (task_type, provider_id) VALUES (?, ?)",
        ("translate", "deepseek"),
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    providers = list_model_providers(db_path)
    defaults = get_provider_defaults(db_path)
    gemini = next(item for item in providers if item["id"] == "gemini")

    assert gemini["label"] == "Operator Gemini"
    assert gemini["base_url"] == "https://operator.example/v1"
    assert gemini["model"] == "operator-model"
    assert gemini["api_key_env"] == "OPERATOR_KEY"
    assert gemini["temperature"] == 0
    assert gemini["timeout_seconds"] == 90
    assert gemini["supports_streaming"] == 0
    assert gemini["supports_batch"] == 0
    assert gemini["cost_input_per_1m"] == 0
    assert gemini["cost_output_per_1m"] == 0
    assert gemini["notes"] == "operator custom notes"
    assert defaults["translate"] == "deepseek"


def test_default_free_and_local_models_match_plan(temp_db_path: Path) -> None:
    init_db(temp_db_path)

    providers = list_model_providers(temp_db_path)
    openrouter = next(item for item in providers if item["id"] == "openrouter")
    ollama = next(item for item in providers if item["id"] == "ollama")

    assert openrouter["model"] == "openrouter/free"
    assert openrouter["cost_input_per_1m"] == 0
    assert openrouter["cost_output_per_1m"] == 0
    assert ollama["model"] == "qwen3:14b"
    assert ollama["cost_input_per_1m"] == 0
    assert ollama["cost_output_per_1m"] == 0


def test_provider_defaults_and_usage_summary(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
        api_key_env="DEEPSEEK_API_KEY",
        cost_input_per_1m=0.14,
        cost_output_per_1m=0.28,
        enabled=1,
    )

    defaults = get_provider_defaults(temp_db_path)
    assert defaults["translate"] == "gemini"
    assert defaults["qa"] == "deepseek"

    record_provider_usage(
        temp_db_path,
        provider_id="deepseek",
        model="deepseek-v4-flash",
        task_type="translate",
        prompt_tokens=1000,
        completion_tokens=1200,
        estimated_cost_usd=0.000476,
        job_id="job-1",
        chapter_id=10,
    )
    record_provider_usage(
        temp_db_path,
        provider_id="deepseek",
        model="deepseek-v4-flash",
        task_type="qa",
        prompt_tokens=500,
        completion_tokens=700,
        estimated_cost_usd=0.000266,
        job_id="job-2",
        chapter_id=11,
    )
    summary = get_usage_summary(temp_db_path)

    assert summary["total_prompt_tokens"] == 1500
    assert summary["total_completion_tokens"] == 1900
    assert summary["total_tokens"] == 3400
    assert summary["total_estimated_cost_usd"] == 0.000742


from app.mobile_api.services.provider_service import ProviderService


def make_provider_service(db_path: Path) -> ProviderService:
    service = object.__new__(ProviderService)
    service.db_path = db_path
    return service


def test_estimate_translation_job_cost_uses_provider_rates(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="cheap",
        label="Cheap",
        base_url="https://example.invalid/v1",
        model="cheap-model",
        api_key_env="CHEAP_API_KEY",
        cost_input_per_1m=0.10,
        cost_output_per_1m=0.40,
        enabled=1,
    )
    service = make_provider_service(temp_db_path)

    estimate = service.estimate_cost(
        provider_id="cheap",
        source_chars=10_000,
        chapter_count=3,
        prompt_overhead_tokens=1500,
    )

    assert estimate == {
        "provider_id": "cheap",
        "model": "cheap-model",
        "chapter_count": 3,
        "estimated_input_tokens": 11166,
        "estimated_output_tokens": 8332,
        "estimated_cost_usd": 0.004449,
        "within_budget": True,
    }


def test_estimate_marks_over_budget(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = make_provider_service(temp_db_path)

    estimate = service.estimate_cost(
        provider_id="gemini",
        source_chars=500_000,
        chapter_count=100,
        max_cost_usd=0.001,
    )

    assert estimate["within_budget"] is False


def test_list_get_defaults_usage_summary_surface_db_helpers(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    record_provider_usage(
        temp_db_path,
        provider_id="gemini",
        model="gemini-2.5-flash-lite",
        task_type="translate",
        prompt_tokens=200,
        completion_tokens=300,
        estimated_cost_usd=0.00014,
        job_id="job-service",
        chapter_id=99,
    )
    service = make_provider_service(temp_db_path)

    providers = service.list_providers()
    provider = service.get_provider("gemini")
    defaults = service.get_defaults()
    summary = service.usage_summary()

    assert {item["id"] for item in providers} >= {"gemini", "deepseek", "openrouter", "ollama"}
    assert provider is not None
    assert provider["id"] == "gemini"
    assert provider["model"] == "gemini-2.5-flash-lite"
    assert service.get_provider("missing") is None
    assert defaults["translate"] == "gemini"
    assert defaults["qa"] == "deepseek"
    assert summary == {
        "total_prompt_tokens": 200,
        "total_completion_tokens": 300,
        "total_tokens": 500,
        "total_estimated_cost_usd": 0.00014,
    }


def test_test_provider_uses_openai_compatible_request_and_parses_content(
    temp_db_path: Path,
    monkeypatch,
) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="custom",
        label="Custom",
        base_url="https://provider.example/v1/",
        model="custom-model",
        api_key_env="CUSTOM_API_KEY",
        temperature=0.7,
        timeout_seconds=42,
    )
    monkeypatch.setenv("CUSTOM_API_KEY", "provider-secret")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "  Xin chao tu provider.  ",
                        },
                    },
                ],
            }

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("app.mobile_api.services.provider_service.requests.post", fake_post)
    service = make_provider_service(temp_db_path)

    result = service.test_provider("custom", "Say hello")

    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer provider-secret"}
    assert captured["json"] == {
        "model": "custom-model",
        "messages": [{"role": "user", "content": "Say hello"}],
        "temperature": 0.7,
        "stream": False,
    }
    assert captured["timeout"] == 42
    assert result == {
        "provider_id": "custom",
        "model": "custom-model",
        "ok": True,
        "sample": "Xin chao tu provider.",
    }


def test_test_provider_rejects_required_provider_with_whitespace_api_key(
    temp_db_path: Path,
    monkeypatch,
) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="custom",
        label="Custom",
        base_url="https://provider.example/v1",
        model="custom-model",
        api_key_env="CUSTOM_API_KEY",
    )
    monkeypatch.setenv("CUSTOM_API_KEY", "   ")
    service = make_provider_service(temp_db_path)

    with pytest.raises(ValueError, match="Provider custom requires CUSTOM_API_KEY"):
        service.test_provider("custom", "hello")


def test_service_normalizes_dirty_provider_values(temp_db_path: Path, monkeypatch) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="dirty",
        label="Dirty",
        base_url="https://provider.example/v1",
        model="dirty-model",
        api_key_env="DIRTY_API_KEY",
        cost_input_per_1m=0.10,
        cost_output_per_1m=0.40,
    )
    with sqlite3.connect(str(temp_db_path)) as conn:
        conn.execute(
            """
            UPDATE model_providers
            SET temperature = NULL,
                timeout_seconds = ?,
                supports_streaming = NULL,
                supports_batch = NULL,
                cost_input_per_1m = ?,
                cost_output_per_1m = NULL,
                enabled = NULL
            WHERE id = ?
            """,
            ("   ", "   ", "dirty"),
        )
        conn.commit()
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url: str, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv("DIRTY_API_KEY", "dirty-secret")
    monkeypatch.setattr("app.mobile_api.services.provider_service.requests.post", fake_post)
    service = make_provider_service(temp_db_path)

    estimate = service.estimate_cost(provider_id="dirty", source_chars=100)
    provider = service.get_provider("dirty")
    service.test_provider("dirty", "hello")

    assert estimate["estimated_cost_usd"] == 0
    assert provider is not None
    assert provider["temperature"] == 0.3
    assert provider["timeout_seconds"] == 180
    assert provider["supports_streaming"] == 0
    assert provider["supports_batch"] == 0
    assert provider["cost_input_per_1m"] == 0
    assert provider["cost_output_per_1m"] == 0
    assert provider["enabled"] == 1
    assert captured["json"]["temperature"] == 0.3
    assert captured["timeout"] == 180


def test_estimate_budget_uses_rounded_cost(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    put_model_provider(
        temp_db_path,
        provider_id="rounding",
        label="Rounding",
        base_url="https://example.invalid/v1",
        model="rounding-model",
        cost_input_per_1m=0.000001,
        cost_output_per_1m=0.000001,
    )
    service = make_provider_service(temp_db_path)

    estimate = service.estimate_cost(
        provider_id="rounding",
        source_chars=1,
        chapter_count=1,
        prompt_overhead_tokens=0,
        max_cost_usd=0,
    )

    assert estimate["estimated_cost_usd"] == 0
    assert estimate["within_budget"] is True


def test_test_provider_raises_value_error_for_missing_provider(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = make_provider_service(temp_db_path)

    with pytest.raises(ValueError, match="Provider missing not found"):
        service.test_provider("missing", "hello")


def test_estimate_cost_raises_value_error_for_missing_provider(temp_db_path: Path) -> None:
    init_db(temp_db_path)
    service = make_provider_service(temp_db_path)

    with pytest.raises(ValueError, match="Provider missing not found"):
        service.estimate_cost(provider_id="missing", source_chars=100)


def test_services_package_exports_provider_service_lazily() -> None:
    from app.mobile_api.services import ProviderService as ExportedProviderService

    assert ExportedProviderService is ProviderService
