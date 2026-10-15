"""Provider and cache regressions use isolated data and synthetic responses."""
import json

import pytest
import requests

from app.database.db import add_book, init_db
from app.translation import ollama_client as llm


@pytest.fixture
def translation_input(tmp_path, monkeypatch):
    init_db(tmp_path / "pipeline.db")
    add_book(tmp_path / "pipeline.db", "Fixture")
    monkeypatch.setattr(llm.settings, "data_dir", tmp_path)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    return dict(text="测试文本。", book_title="Fixture", chapter_title="第一章", chapter_number=1,
                model="fixture", host="https://provider.invalid/v1", api_key="")


def test_translation_does_not_retry_401(translation_input, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = 401
        response._content = b"unauthorized"
        return response
    monkeypatch.setattr(llm.requests, "post", post)
    with pytest.raises(llm.TranslationError):
        llm.translate_chapter(**translation_input, use_cache=False)
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [
    {"choices": []},
    {"choices": [{"message": {"content": " "}}]},
    {"choices": [{"message": {"content": "Một đoạn bị cắt"}, "finish_reason": "length"}]},
])
def test_provider_rejects_invalid_output(payload, monkeypatch):
    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr(llm.requests, "post", post)
    with pytest.raises(llm.TranslationError):
        llm.call_openai_compatible_chat(prompt="Fixture", base_url="https://provider.invalid/v1", model="fixture")


def test_cache_tracks_effective_style_and_provider(translation_input, monkeypatch):
    calls = []
    profile = {"id": "fixture", "prompt_rules": "Quy tắc ban đầu"}
    monkeypatch.setattr(llm, "get_default_style_profile", lambda _: profile)
    def post(*args, **kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"choices": [{"message": {"content": "Bản dịch hợp lệ."}}]}).encode()
        return response
    monkeypatch.setattr(llm.requests, "post", post)
    llm.translate_chapter(**translation_input)
    llm.translate_chapter(**translation_input)
    assert len(calls) == 1
    profile["prompt_rules"] = "Quy tắc mới"
    llm.translate_chapter(**translation_input)
    assert len(calls) == 2
    translation_input["host"] = "https://another-provider.invalid/v1"
    llm.translate_chapter(**translation_input)
    assert len(calls) == 3


def test_incomplete_translation_markup_is_not_published():
    with pytest.raises(llm.TranslationError):
        llm._extract_clean_translation("<TRANSLATION>Bản dịch bị cắt.", 1)
