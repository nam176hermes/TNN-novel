from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path


def test_settings_read_environment_overrides() -> None:
    keys = {
        "OLLAMA_HOST": "http://example.invalid/v1",
        "OLLAMA_MODEL": "env-model",
        "OLLAMA_API_KEY": "env-key",
        "OLLAMA_TEMPERATURE": "0.7",
        "OLLAMA_CHUNK_SIZE": "1234",
        "OLLAMA_TIMEOUT": "45",
        "EDGE_TTS_VOICE": "vi-VN-NamMinhNeural",
        "DATA_DIR": "/tmp/novel-pipeline-test-data",
        "LOG_LEVEL": "DEBUG",
    }
    old_values = {key: os.environ.get(key) for key in keys}

    try:
        os.environ.update(keys)
        import app.config as config_mod

        reloaded = importlib.reload(config_mod)

        assert reloaded.settings.ollama_host == "http://example.invalid/v1"
        assert reloaded.settings.ollama_model == "env-model"
        assert reloaded.settings.ollama_api_key == "env-key"
        assert reloaded.settings.ollama_temperature == 0.7
        assert reloaded.settings.ollama_chunk_size == 1234
        assert reloaded.settings.ollama_timeout == 45
        assert reloaded.settings.edge_tts_voice == "vi-VN-NamMinhNeural"
        assert reloaded.settings.data_dir == Path("/tmp/novel-pipeline-test-data")
        assert reloaded.settings.log_level == "DEBUG"
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        import app.config as config_mod

        importlib.reload(config_mod)


def test_effective_default_chunk_size_is_optimized_for_api_translation() -> None:
    old_value = os.environ.get("OLLAMA_CHUNK_SIZE")

    try:
        os.environ.pop("OLLAMA_CHUNK_SIZE", None)
        import app.config as config_mod

        reloaded = importlib.reload(config_mod)

        assert reloaded.settings.ollama_chunk_size == 3500
    finally:
        if old_value is None:
            os.environ.pop("OLLAMA_CHUNK_SIZE", None)
        else:
            os.environ["OLLAMA_CHUNK_SIZE"] = old_value

        import app.config as config_mod

        importlib.reload(config_mod)


def test_relative_data_dir_resolves_from_project_root() -> None:
    old_value = os.environ.get("DATA_DIR")

    try:
        os.environ["DATA_DIR"] = "relative-test-data"
        import app.config as config_mod

        reloaded = importlib.reload(config_mod)

        assert reloaded.settings.data_dir == Path("relative-test-data")
        assert reloaded.settings.resolved_data_dir == reloaded.PROJECT_ROOT / "relative-test-data"
        assert reloaded.settings.db_path == reloaded.PROJECT_ROOT / "relative-test-data" / "pipeline.db"
    finally:
        if old_value is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old_value

        import app.config as config_mod

        importlib.reload(config_mod)


def test_runtime_data_helpers_do_not_depend_on_cwd(tmp_path, monkeypatch) -> None:
    old_value = os.environ.get("DATA_DIR")
    data_dir_name = "relative-runtime-test-data"

    try:
        os.environ["DATA_DIR"] = data_dir_name
        import app.config as config_mod

        reloaded_config = importlib.reload(config_mod)
        canonical_dir = reloaded_config.PROJECT_ROOT / data_dir_name
        shutil.rmtree(canonical_dir, ignore_errors=True)

        import app.ingestion.importers as importers_mod
        import app.main as main_mod
        import app.scheduler.daily_queue as daily_queue_mod
        import app.ui.web_dashboard as web_dashboard_mod

        importlib.reload(importers_mod)
        importlib.reload(main_mod)
        importlib.reload(daily_queue_mod)
        importlib.reload(web_dashboard_mod)

        monkeypatch.chdir(tmp_path)

        assert main_mod._ensure_data_dir() == canonical_dir
        assert web_dashboard_mod._ensure_data_dir() == canonical_dir
        assert importers_mod._data_dir() == canonical_dir

        daily_queue_mod.save_daily_report(canonical_dir / "pipeline.db", {"date": "2099-01-01"})
        assert (canonical_dir / "logs" / "daily_reports" / "daily_2099-01-01.json").exists()
        assert not (tmp_path / data_dir_name).exists()
    finally:
        if old_value is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old_value

        import app.config as config_mod

        importlib.reload(config_mod)
        shutil.rmtree(config_mod.PROJECT_ROOT / data_dir_name, ignore_errors=True)


def test_mobile_api_data_dir_creates_reader_dictionary_directory(tmp_path, monkeypatch) -> None:
    from app.mobile_api import dependencies

    monkeypatch.setattr(dependencies.settings, "data_dir", tmp_path)

    data_dir = dependencies.get_data_dir()

    assert data_dir == tmp_path
    assert (data_dir / "dictionaries").is_dir()
