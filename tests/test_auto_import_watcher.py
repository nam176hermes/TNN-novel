from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_watcher_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "auto_import_watcher.py"
    spec = importlib.util.spec_from_file_location("auto_import_watcher_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configured_watch_dir_uses_explicit_portable_environment(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_IMPORT_WATCH_DIR", "/srv/novel-tnn/inbox")
    watcher = _load_watcher_module()

    assert watcher.configured_watch_dir() == Path("/srv/novel-tnn/inbox")


def test_scan_and_import_uses_explicit_directory_without_windows_mount(tmp_path: Path, monkeypatch) -> None:
    watcher = _load_watcher_module()
    watch_dir = tmp_path / "inbox"
    watch_dir.mkdir()
    monkeypatch.setattr(watcher, "log", lambda _message: None)

    assert watcher.scan_and_import(watch_dir) == {"imported": 0, "skipped": 0, "errors": 0, "total": 0}
