from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_smoke_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "smoke_reader_authenticated.py"
    spec = importlib.util.spec_from_file_location("smoke_reader_authenticated_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_authenticated_reader_smoke_only_reads_after_login() -> None:
    module = _load_smoke_module()
    calls: list[tuple[str, str]] = []

    def request_json(method: str, url: str, **_kwargs: Any) -> Any:
        calls.append((method, url))
        path = url.removeprefix("https://reader.example.test")
        responses = {
            ("POST", "/api/auth/login"): {"access_token": "reader-smoke-token"},
            ("GET", "/api/library/books"): {"books": [{"id": 7}]},
            ("GET", "/api/books/7/chapters"): [
                {"id": 11, "status": "translated", "translated_text_path": "available"}
            ],
            ("GET", "/api/books/7/reader/state"): {"book_id": 7, "progress": None},
            ("GET", "/api/books/7/chapters/11"): {"id": 11, "book_id": 7},
            ("GET", "/api/books/7/chapters/11/translation"): {
                "chapter_id": 11,
                "missing": False,
                "text": "Nội dung đã dịch.",
            },
        }
        return responses[(method, path)]

    result = module.run_authenticated_reader_smoke(
        api_base_url="https://reader.example.test",
        username="operator",
        password="not-logged",
        request=request_json,
    )

    assert result.book_id == 7
    assert result.chapter_id == 11
    assert result.translation_characters == len("Nội dung đã dịch.")
    assert calls[0] == ("POST", "https://reader.example.test/api/auth/login")
    assert all(method == "GET" for method, _url in calls[1:])
    assert {url for _method, url in calls[1:]} == {
        "https://reader.example.test/api/library/books",
        "https://reader.example.test/api/books/7/chapters",
        "https://reader.example.test/api/books/7/reader/state",
        "https://reader.example.test/api/books/7/chapters/11",
        "https://reader.example.test/api/books/7/chapters/11/translation",
    }


def test_authenticated_reader_smoke_refuses_insecure_public_endpoint() -> None:
    module = _load_smoke_module()

    try:
        module.validate_api_base_url("http://reader.example.test")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected public HTTP endpoint to be rejected")
