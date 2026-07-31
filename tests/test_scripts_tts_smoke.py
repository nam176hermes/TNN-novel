from __future__ import annotations

import importlib.util
import py_compile
import sys
import tempfile
from pathlib import Path

from app.database.db import add_book, add_chapter, init_db, update_chapter_paths


def _load_smoke_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_tts_audio.py"
    spec = importlib.util.spec_from_file_location("smoke_tts_audio_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_book(temp_db_path: Path, tmp_path: Path) -> tuple[int, int]:
    init_db(temp_db_path)
    data_dir = tmp_path / "data"
    translated_dir = data_dir / "translated"
    translated_dir.mkdir(parents=True, exist_ok=True)
    book_id = add_book(temp_db_path, "Smoke Real Provider", author="Tester")
    chapter_id = add_chapter(temp_db_path, book_id, 1, "Chương 1")
    translated_path = translated_dir / "chapter-1.txt"
    translated_path.write_text("Một đoạn tiếng Việt để kiểm tra smoke TTS.", encoding="utf-8")
    update_chapter_paths(temp_db_path, chapter_id, translated_text_path=translated_path, status="translated")
    return book_id, chapter_id


def test_smoke_tts_audio_script_compiles() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_tts_audio.py"
    py_compile.compile(str(script), doraise=True)


def test_real_provider_dry_run_does_not_invoke_provider(temp_db_path: Path, tmp_path: Path, monkeypatch) -> None:
    module = _load_smoke_module()
    book_id, _chapter_id = _prepare_book(temp_db_path, tmp_path)
    output_dir = tmp_path / "validation"

    def forbidden_generate(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run must not invoke TTSPipeline.generate_chapter")

    monkeypatch.setattr(module.TTSPipeline, "generate_chapter", forbidden_generate)

    exit_code = module.main(
        [
            "--real-provider",
            "--dry-run",
            "--db-path",
            str(temp_db_path),
            "--data-dir",
            str(tmp_path / "data"),
            "--book-id",
            str(book_id),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "tts-operational-report.md").exists()


def test_build_real_provider_plan_enforces_max_chars(temp_db_path: Path, tmp_path: Path) -> None:
    module = _load_smoke_module()
    book_id, _chapter_id = _prepare_book(temp_db_path, tmp_path)

    try:
        module.build_real_provider_plan(
            db_path=temp_db_path,
            book_id=book_id,
            chapter_id=None,
            chapter_limit=1,
            max_chars=5,
        )
    except ValueError as exc:
        assert "exceeding --max-chars limit" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected max char guard to fail")


def test_real_provider_requires_required_scope_flags(tmp_path: Path) -> None:
    module = _load_smoke_module()
    exit_code = module.main(["--real-provider", "--db-path", str(tmp_path / "missing.db")])
    assert exit_code == 1


def test_real_provider_refuses_existing_audio_without_overwrite(temp_db_path: Path, tmp_path: Path, monkeypatch) -> None:
    module = _load_smoke_module()
    book_id, chapter_id = _prepare_book(temp_db_path, tmp_path)
    audio_path = tmp_path / "data" / "audio" / "existing.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"existing-audio")
    update_chapter_paths(temp_db_path, chapter_id, audio_path=audio_path, status="audio_done")

    def forbidden_generate(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("existing audio should block before provider generation")

    monkeypatch.setattr(module.TTSPipeline, "generate_chapter", forbidden_generate)
    results, _, _, report_path = module.run_real_provider_smoke(
        db_path=temp_db_path,
        data_dir=tmp_path / "data",
        book_id=book_id,
        chapter_id=chapter_id,
        chapter_limit=1,
        max_chars=None,
        provider=None,
        voice_payload={},
        output_dir=tmp_path / "validation",
        generate_m4b=False,
        dry_run=False,
        resume=False,
        overwrite=False,
        yes=True,
    )

    assert any((not item.ok) and "already has audio" in item.message for item in results)
    assert report_path.exists()


def test_validation_report_redacts_secrets(tmp_path: Path) -> None:
    module = _load_smoke_module()
    report_path = module._write_validation_report(
        output_dir=tmp_path,
        mode="dry-run",
        plan={
            "book_id": 1,
            "book_title": "Book",
            "chapter_count": 1,
            "estimated_characters": 100,
            "estimated_chunks": 2,
        },
        preflight={
            "provider": "f5_vietnamese",
            "voice": {"voice_id": "default", "rate": "-5%", "volume": "+0%"},
            "ffmpeg_available": True,
            "ffprobe_available": True,
            "estimated_storage_bytes": 1024,
            "warnings": ["api_key=secret123 /tmp/private/path"],
        },
        chapter_plans=[],
        results=[],
        mp3_reports=[],
        m4b_report=None,
        route_results=[],
    )

    text = report_path.read_text(encoding="utf-8")
    json_text = (tmp_path / "tts-operational-report.json").read_text(encoding="utf-8")
    assert "secret123" not in text
    assert "[redacted]" in text
    assert "/tmp/private/path" not in text
    assert "secret123" not in json_text
    assert "/tmp/private/path" not in json_text


def test_live_route_validation_requires_a_secure_password_file() -> None:
    module = _load_smoke_module()
    with tempfile.TemporaryDirectory(dir="/tmp") as root:
        password_file = Path(root) / "password.txt"
        password_file.write_text("secret-password\n", encoding="utf-8")
        password_file.chmod(0o600)

        assert module._read_smoke_password(password_file) == "secret-password"

        password_file.chmod(0o644)
        try:
            module._read_smoke_password(password_file)
        except ValueError as exc:
            assert "permissions" in str(exc).lower()
        else:  # pragma: no cover
            raise AssertionError("expected insecure password file to be rejected")


def test_live_route_validation_uses_streaming_requests_and_requires_https(monkeypatch) -> None:
    module = _load_smoke_module()
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}

        def json(self) -> dict:
            return self._payload

        def iter_bytes(self, **_kwargs):
            yield b"audio-prefix"

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url: str, **_kwargs) -> FakeResponse:
            calls.append(("post", url))
            return FakeResponse(200, {"access_token": "test-token"})

        def stream(self, method: str, url: str, **_kwargs) -> FakeResponse:
            calls.append((method.lower(), url))
            headers = _kwargs.get("headers") or {}
            return FakeResponse(401 if "Authorization" not in headers else 200)

        def get(self, *_args, **_kwargs):
            raise AssertionError("route smoke must not buffer complete audio responses via get")

    monkeypatch.setattr(module.httpx, "Client", FakeClient)

    results = module.run_server_route_smoke(
        base_url="https://example.test",
        username="operator",
        password="secret",
        book_id=7,
        chapter_id=9,
        check_m4b_route=True,
    )

    assert all(item.ok for item in results)
    assert any(method == "get" and "/audio" in url for method, url in calls)
    try:
        module._validate_live_base_url("http://example.test")
    except ValueError as exc:
        assert "https" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected non-local HTTP base URL to be rejected")


def test_validation_report_records_protected_route_results(tmp_path: Path) -> None:
    module = _load_smoke_module()
    report_path = module._write_validation_report(
        output_dir=tmp_path,
        mode="dry-run",
        plan={"book_id": 1, "book_title": "Book", "chapter_count": 1, "estimated_characters": 1, "estimated_chunks": 1},
        preflight={"provider": "f5_vietnamese", "voice": {"voice_id": "default"}, "ffmpeg_available": True, "ffprobe_available": True, "estimated_storage_bytes": 1, "warnings": []},
        chapter_plans=[],
        results=[],
        mp3_reports=[],
        m4b_report=None,
        route_results=[],
    )

    module.update_validation_report_routes(
        report_path,
        [module._pass("authenticated audio stream returned 200")],
    )

    assert "authenticated audio stream returned 200" in report_path.read_text(encoding="utf-8")
    report_json = (tmp_path / "tts-operational-report.json").read_text(encoding="utf-8")
    assert "authenticated audio stream returned 200" in report_json
