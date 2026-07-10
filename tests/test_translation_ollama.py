from __future__ import annotations

import json

import pytest
from requests import Response
from rich.errors import LiveError

from app.translation import ollama_client
from app.translation.ollama_client import (
    _build_translation_prompt,
    _extract_new_terms,
    _postprocess_translation,
    _pre_substitute_glossary_terms,
    _split_into_chunks,
    _translation_status,
    call_llm,
    translate_chapter,
)


def test_call_openai_compatible_chat_uses_provider_settings(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "  bản dịch  "}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    result = ollama_client.call_openai_compatible_chat(
        prompt="dịch",
        base_url="https://example.invalid/v1/",
        model="cheap-model",
        api_key=" secret ",
        temperature=0.2,
        timeout=12,
    )

    assert captured["url"] == "https://example.invalid/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["json"] == {
        "model": "cheap-model",
        "messages": [{"role": "user", "content": "dịch"}],
        "temperature": 0.2,
        "stream": False,
    }
    assert captured["timeout"] == 12
    assert result == {
        "text": "bản dịch",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_translation_status_ignores_rich_live_conflict(monkeypatch) -> None:
    events: list[str] = []

    class FakeStatus:
        def __enter__(self):
            raise LiveError("Only one live display may be active at once")

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("exit")

    class FakeConsole:
        is_terminal = True

        def status(self, message: str) -> FakeStatus:
            events.append(message)
            return FakeStatus()

    monkeypatch.setattr(ollama_client, "console", FakeConsole())

    with _translation_status("Translating chunks"):
        events.append("translated")

    assert events == ["Translating chunks", "translated"]


def test_call_openai_compatible_chat_omits_blank_authorization(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, headers, json, timeout):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    ollama_client.call_openai_compatible_chat(
        prompt="dịch",
        base_url="https://example.invalid/v1",
        model="cheap-model",
        api_key="   ",
    )

    assert captured["headers"] == {}


def test_call_openai_compatible_chat_retries_transient_503(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    call_count = 0

    def fake_post(url, headers, json, timeout):
        nonlocal call_count
        call_count += 1
        response = Response()
        response.url = url
        if call_count == 1:
            response.status_code = 503
            response._content = b"Service Unavailable"
            return response
        response.status_code = 200
        response._content = b'{"choices":[{"message":{"content":"ok after retry"}}]}'
        return response

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    result = ollama_client.call_openai_compatible_chat(
        prompt="dịch",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash-lite",
        api_key="secret",
    )

    assert call_count == 2
    assert result["text"] == "ok after retry"


def test_call_llm_records_provider_usage_when_metadata_is_supplied(monkeypatch, tmp_path) -> None:
    from app.database.db import get_usage_summary, init_db

    db_path = tmp_path / "pipeline.db"
    init_db(db_path)
    captured: dict[str, object] = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {
            "text": "Bản dịch đã sửa.",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    monkeypatch.setattr(ollama_client, "call_openai_compatible_chat", fake_chat)

    result = call_llm(
        "prompt",
        model="gemini-2.5-flash-lite",
        host="https://provider.example/v1",
        api_key="provider-secret",
        db_path=db_path,
        provider_id="gemini",
        task_type="polish",
        job_id="job-polish",
        chapter_id=7,
    )

    assert result == "Bản dịch đã sửa."
    assert captured["api_key"] == "provider-secret"
    assert get_usage_summary(db_path) == {
        "total_prompt_tokens": 1000,
        "total_completion_tokens": 500,
        "total_tokens": 1500,
        "total_estimated_cost_usd": 0.0003,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": "not-a-list"},
    ],
)
def test_call_openai_compatible_chat_returns_empty_text_for_malformed_response(
    monkeypatch,
    payload,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    def fake_post(url, headers, json, timeout):
        return FakeResponse()

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    result = ollama_client.call_openai_compatible_chat(
        prompt="dịch",
        base_url="https://example.invalid/v1",
        model="cheap-model",
    )

    assert result == {"text": "", "usage": {}}


class TestSplitIntoChunks:
    def test_short_text_returns_single_chunk(self):
        text = "段落一。\n\n段落二。\n\n段落三。"
        chunks = _split_into_chunks(text, max_chars=5000)
        assert len(chunks) == 1
        assert "段落一" in chunks[0]
        assert "段落二" in chunks[0]

    def test_splits_at_paragraph_boundary(self):
        # Each paragraph ~1000 chars, max_chars=1500 means each gets its own chunk
        para_a = "天地玄黄，宇宙洪荒。" * 100  # ~1000 chars
        para_b = "日月盈昃，辰宿列张。" * 100  # ~1000 chars
        text = f"{para_a}\n\n{para_b}"
        chunks = _split_into_chunks(text, max_chars=1500)
        assert len(chunks) == 2
        assert para_a in chunks[0]
        assert para_b in chunks[1]

    def test_three_paragraphs_split_correctly(self):
        # Three paragraphs ~600 chars each, max_chars=1000 -> each paragraph becomes its own chunk
        para = "abcdefghij" * 60  # 600 chars
        text = f"{para}\n\n{para}\n\n{para}"
        chunks = _split_into_chunks(text, max_chars=1000)
        assert len(chunks) == 3
        assert chunks == [para, para, para]

    def test_empty_text_returns_empty_list(self):
        assert _split_into_chunks("") == []
        assert _split_into_chunks("   ") == []

    def test_long_single_paragraph_splits_below_limit(self):
        text = "他点了点头。" * 30
        chunks = _split_into_chunks(text, max_chars=40)
        assert len(chunks) > 1
        assert all(len(chunk) <= 40 for chunk in chunks)
        assert "".join(chunks) == text


class TestPostprocessTranslation:
    def test_glossary_marker_keeps_vietnamese_locked_term(self):
        text = "Hắn cầm 太阳石【Thái Dương Thạch】 trong tay."
        result = _postprocess_translation(text)
        assert "Thái Dương Thạch" in result
        assert "太阳石" not in result
        assert "Hắn cầm Thái Dương Thạch trong tay." == result

    def test_removes_empty_parentheses_left_by_cjk_cleanup(self):
        text = "Hắn đã đạt tới Kim Đan (金丹)."
        result = _postprocess_translation(text)
        assert result == "Hắn đã đạt tới Kim Đan."

    def test_preserves_family_compound_anh_at_sentence_start(self):
        text = "Anh cả khẽ gật đầu. Anh đi vào phòng. Người anh trai kia im lặng."
        result = _postprocess_translation(text)
        assert "Anh cả khẽ gật đầu" in result
        assert "Hắn đi vào phòng" in result
        assert "người anh trai kia im lặng" in result.lower()

    def test_removes_new_terms_section(self):
        text = "Hắn bước vào thế giới tu chân.\n\nNEW_TERMS\n修真: tu chân\n灵石: linh thạch"
        result = _postprocess_translation(text)
        assert "Hắn bước vào thế giới tu chân" in result
        assert "NEW_TERMS" not in result
        assert "修真" not in result

    def test_removes_new_terms_colon_variant(self):
        text = "Hắn bước vào thế giới tu chân.\n\nNEW_TERMS:\n修真: tu chân"
        result = _postprocess_translation(text)
        assert "NEW_TERMS" not in result
        assert "修真" not in result

    def test_removes_known_fragments(self):
        text = "Hắn 暗暗下定了决心 眼看 liền đi."
        result = _postprocess_translation(text)
        assert "暗暗下定了决心" not in result
        assert "眼看" not in result
        assert "Hắn" in result
        assert "liền đi" in result

    def test_normalizes_pronouns(self):
        text = "Anh đi vào phòng. anh ta nói."
        result = _postprocess_translation(text)
        assert "Hắn đi vào phòng" in result  # Anh at start -> Hắn
        assert "hắn ta nói" in result  # anh -> hắn

    def test_collapses_excess_blank_lines(self):
        text = "Dòng 1\n\n\n\n\nDòng 2"
        result = _postprocess_translation(text)
        assert "\n\n\n" not in result
        assert result == "Dòng 1\n\nDòng 2"

    def test_removes_repeated_garbage(self):
        text = "Dòng aaaaaaabbbbbbb"
        result = _postprocess_translation(text)
        # 3+ repeats of same char removed
        assert "aaaaaa" not in result

    def test_collapses_repeated_characters_without_deleting_word(self):
        text = "Hắn laaaaaa lên."
        result = _postprocess_translation(text)
        assert result == "Hắn laaa lên."


class TestBuildTranslationPrompt:
    def test_glossary_and_summary_included(self):
        prompt = _build_translation_prompt(
            chunk="测试文本 世界",
            book_title="仙侠世界",
            chapter_title="第一章",
            glossary={"测试": "trắc nghiệm", "世界": "thế giới"},
            previous_summary="Nhân vật chính thức tỉnh.",
        )
        assert "trắc nghiệm" in prompt
        assert "thế giới" in prompt
        assert "Nhân vật chính thức tỉnh" in prompt
        assert "测试文本 世界" in prompt

    def test_empty_glossary_shows_none(self):
        prompt = _build_translation_prompt(
            chunk="测试",
            book_title="Test",
            chapter_title="Ch1",
            glossary={},
            previous_summary="",
        )
        assert "(none)" in prompt

    def test_glossary_filters_to_relevant_terms_only(self):
        """Only terms present in the chunk should appear in the prompt."""
        prompt = _build_translation_prompt(
            chunk="测试文本",
            book_title="Test",
            chapter_title="Ch1",
            glossary={"测试": "trắc nghiệm", "不存在": "không tồn tại"},
            previous_summary="",
        )
        assert "trắc nghiệm" in prompt
        assert "không tồn tại" not in prompt

    def test_previous_suffix_only_terms_do_not_pollute_current_prompt(self):
        prompt = _build_translation_prompt(
            chunk="他转身离开。",
            book_title="Test",
            chapter_title="Ch1",
            glossary={"灵石": "linh thạch"},
            previous_summary="",
            previous_chunk_suffix="他刚才捡到一块灵石。",
        )
        assert "Glossary:\n(none)" in prompt
        assert "Glossary:\n灵石: linh thạch" not in prompt

    def test_cross_boundary_terms_are_still_included(self):
        prompt = _build_translation_prompt(
            chunk="石忽然亮了。",
            book_title="Test",
            chapter_title="Ch1",
            glossary={"灵石": "linh thạch"},
            previous_summary="",
            previous_chunk_suffix="他握住那块灵",
        )
        assert "Glossary:\n灵石: linh thạch" in prompt

    def test_prompt_forbids_modern_pronouns_in_classical_address(self):
        prompt = _build_translation_prompt(
            chunk="六哥，这些天多亏了你照顾，我还不知道怎么报答，请不要再给我东西了。",
            book_title="永夜",
            chapter_title="第一章",
            glossary={},
            previous_summary="",
        )

        assert "Không dùng \"tôi\" khi nhân vật đang gọi Lục ca" in prompt
        assert "Lục ca, mấy ngày nay nhờ huynh chăm sóc" in prompt
        assert "xin huynh đừng cho ta thêm đồ nữa" in prompt
        assert "Lục ca, mấy ngày nay đã phiền hắn chăm sóc" in prompt

    def test_prompt_few_shots_do_not_teach_modern_anh_ta_default(self):
        prompt = _build_translation_prompt(
            chunk="他只是稍微平复情绪，然后继续观察周围的情况。",
            book_title="Test",
            chapter_title="Ch1",
            glossary={},
            previous_summary="",
        )

        assert "anh ta tiếp tục quan sát" not in prompt
        assert "hắn tiếp tục quan sát" in prompt

    def test_style_profile_and_locked_terms_are_included(self):
        prompt = _build_translation_prompt(
            chunk="他拿起灵石，准备筑基。",
            book_title="Test",
            chapter_title="Ch1",
            glossary={"灵石": "linh thạch", "筑基": "Trúc Cơ"},
            previous_summary="",
            style_profile={
                "id": "tien_hiep",
                "label": "Tiên hiệp",
                "pronoun_rules": "Dùng ta/ngươi, tiền bối/vãn bối.",
                "han_viet_level": "high",
                "preferred_terms": "tu vi, cảnh giới, linh khí",
                "banned_modern_terms": "tôi, bạn, level up",
                "prompt_rules": "Giữ văn phong cổ trang tu luyện.",
            },
            locked_glossary_terms=[
                {
                    "source_term": "筑基",
                    "target_term": "Trúc Cơ",
                    "term_type": "realm",
                    "genre": "tien_hiep",
                    "priority": 50,
                }
            ],
        )

        assert "Style profile: Tiên hiệp (tien_hiep)" in prompt
        assert "Dùng ta/ngươi, tiền bối/vãn bối." in prompt
        assert "Han-Viet level: high" in prompt
        assert "Preferred cổ trang terms: tu vi, cảnh giới, linh khí" in prompt
        assert "Banned modern terms: tôi, bạn, level up" in prompt
        assert "Styleguide genre preset: Tiên hiệp nghiêm túc" in prompt
        assert "Tone: trang trọng, huyền ảo, cổ phong vừa phải" in prompt
        assert "Locked glossary terms:" in prompt
        assert "筑基 -> Trúc Cơ [term_type=realm, genre=tien_hiep, priority=50, LOCKED]" in prompt

    def test_literary_phrase_guidance_is_included_for_relevant_source(self):
        prompt = _build_translation_prompt(
            chunk="他叹道：一举两得，何乐而不为？又吟道：山重水复疑无路，柳暗花明又一村。",
            book_title="Test",
            chapter_title="Ch1",
            glossary={},
            previous_summary="",
        )

        assert "Literary phrase guide:" in prompt
        assert "Thơ, thành ngữ, tục ngữ, đối liên, điển cố" in prompt
        assert "一举两得 -> một công đôi việc" in prompt
        assert "山重水复疑无路，柳暗花明又一村 -> núi sông trùng điệp ngỡ không lối, liễu rậm hoa tươi lại thấy thôn" in prompt
        assert "守株待兔" not in prompt


class TestExtractNewTerms:
    def test_parses_bulleted_xml_terms_without_bullet_in_source(self):
        text = "<TRANSLATION>Bản dịch.</TRANSLATION><NEW_TERMS>\n- 灵石 -> linh thạch\n1. 丹药: đan dược\n</NEW_TERMS>"
        terms = _extract_new_terms(text)
        assert ("灵石", "linh thạch") in terms
        assert ("丹药", "đan dược") in terms
        assert all(not src.startswith(("-", "1.")) for src, _ in terms)

    def test_parses_arrow_format(self):
        text = "Translation.\n\nNEW_TERMS:\n灵石 -> linh thạch\n丹药 -> đan dược"
        terms = _extract_new_terms(text)
        assert ("灵石", "linh thạch") in terms
        assert ("丹药", "đan dược") in terms

    def test_parses_colon_format(self):
        text = "Translation.\n\nNEW_TERMS:\n灵石: linh thạch\n丹药: đan dược"
        terms = _extract_new_terms(text)
        assert ("灵石", "linh thạch") in terms
        assert ("丹药", "đan dược") in terms

    def test_returns_empty_when_no_new_terms(self):
        text = "Just a translation without any NEW_TERMS section."
        assert _extract_new_terms(text) == []

    def test_stops_at_non_term_line(self):
        text = "Translation.\n\nNEW_TERMS:\n灵石 -> linh thạch\nThis is not a term line."
        terms = _extract_new_terms(text)
        assert len(terms) == 1
        assert terms[0] == ("灵石", "linh thạch")


class TestPreSubstituteGlossaryTerms:
    def test_longer_terms_do_not_get_nested_shorter_markers(self):
        text = "太阳石闪耀"
        glossary = {
            "太阳": "Mặt Trời",
            "太阳石": "Thái Dương Thạch",
        }

        result = _pre_substitute_glossary_terms(text, glossary)

        assert result == "太阳石【Thái Dương Thạch】闪耀"


class TestTranslateChapter:
    def test_translate_chapter_success(self, monkeypatch, tmp_path):
        """Test that translate_chapter calls Ollama and processes output."""
        import app.translation.ollama_client as ollama_mod

        # Insert a book
        from app.database.db import add_book, init_db
        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        add_book(db_path, "Test Book")

        def mock_post(*args, **kwargs):
            resp = Response()
            resp.status_code = 200
            # OpenAI-compatible format
            resp._content = json.dumps({
                "choices": [{"message": {"content": "Bản dịch thử nghiệm."}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        result = translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=False,
        )
        assert "Bản dịch thử nghiệm" in result

    def test_translate_chapter_records_provider_usage(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod

        from app.database.db import add_book, get_usage_summary, init_db

        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        add_book(db_path, "Test Book")

        def mock_post(*args, **kwargs):
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(
                {
                    "choices": [{"message": {"content": "Bản dịch có usage."}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                }
            ).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="gemini-2.5-flash-lite",
            provider_id="gemini",
            job_id="job-usage",
            chapter_id=5,
            use_cache=False,
        )

        summary = get_usage_summary(db_path)

        assert summary == {
            "total_prompt_tokens": 1000,
            "total_completion_tokens": 500,
            "total_tokens": 1500,
            "total_estimated_cost_usd": 0.0003,
        }

    def test_translate_chapter_loads_default_profile_and_locked_terms(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod

        from app.database.db import add_book, init_db, put_glossary_term

        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        book_id = add_book(db_path, "Test Book")
        put_glossary_term(
            db_path,
            book_id,
            "灵石",
            "linh thạch",
            mode="translate",
            priority=50,
            locked=1,
            genre="tien_hiep",
            term_type="artifact",
        )
        captured: dict[str, str] = {}

        def mock_post(*args, **kwargs):
            captured["prompt"] = kwargs["json"]["messages"][0]["content"]
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "<TRANSLATION>Hắn cầm linh thạch.</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        translate_chapter(
            text="他拿起灵石。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=False,
        )

        assert "Style profile: Tiên hiệp (tien_hiep)" in captured["prompt"]
        assert "Locked glossary terms:" in captured["prompt"]
        assert "灵石 -> linh thạch [term_type=artifact, genre=tien_hiep, priority=50, LOCKED]" in captured["prompt"]

    def test_translate_chapter_ignores_cache_from_older_prompt_version(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod

        from app.database.db import add_book, init_db
        from app.translation.cache import set_cached_translation

        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        add_book(db_path, "Test Book")
        set_cached_translation(db_path, "测试文本。", "zh", "vi", "test-model", "Bản dịch cache cũ.")

        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "<TRANSLATION>Bản dịch prompt mới.</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        result = translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=True,
        )

        assert result == "Bản dịch prompt mới."
        assert call_count == 1

    def test_translate_chapter_retry_on_error(self, monkeypatch, tmp_path):
        """Test that first failure triggers retry with lower temperature."""
        import app.translation.ollama_client as ollama_mod

        from app.database.db import add_book, init_db
        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        add_book(db_path, "Test Book")

        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                import requests
                raise requests.ConnectionError("Ollama not reachable")
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "Bản dịch sau khi retry."}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        result = translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=False,
        )
        assert "Bản dịch sau khi retry" in result

    def test_translate_chapter_cancel_check_stops_before_next_chunk(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod
        from app.database.db import add_book, init_db
        from app.translation.ollama_client import TranslationError

        db_path = tmp_path / "pipeline.db"
        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(db_path)
        add_book(db_path, "Test Book")
        post_calls = 0
        cancel_checks = 0

        def mock_post(*args, **kwargs):
            nonlocal post_calls
            post_calls += 1
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "<TRANSLATION>Bản dịch chunk.</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"}}]
            }).encode()
            return resp

        def cancel_check() -> bool:
            nonlocal cancel_checks
            cancel_checks += 1
            return cancel_checks > 1

        monkeypatch.setattr("requests.post", mock_post)

        with pytest.raises(TranslationError, match="cancelled"):
            translate_chapter(
                text="第一段内容很多很多。第二段内容很多很多。",
                book_title="Test Book",
                chapter_title="Ch1",
                chapter_number=1,
                model="test-model",
                chunk_size=12,
                use_cache=False,
                cancel_check=cancel_check,
            )

        assert post_calls == 1

    def test_retry_temperature_never_increases_above_initial(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod
        from app.database.db import add_book, init_db

        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        init_db(tmp_path / "pipeline.db")
        add_book(tmp_path / "pipeline.db", "Test Book")
        monkeypatch.setattr("time.sleep", lambda _: None)

        temperatures = []
        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            temperatures.append(kwargs["json"]["temperature"])
            if call_count == 1:
                import requests
                raise requests.ConnectionError("Ollama not reachable")
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "<TRANSLATION>Bản dịch retry.</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            temperature=0.05,
            use_cache=False,
        )

        assert temperatures == [0.05, 0.0]

    def test_retry_success_extracts_new_terms(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod
        from app.database.db import add_book, get_connection, init_db

        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        db_path = tmp_path / "pipeline.db"
        init_db(db_path)
        add_book(db_path, "Test Book")
        monkeypatch.setattr("time.sleep", lambda _: None)

        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                import requests
                raise requests.ConnectionError("Ollama not reachable")
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps({
                "choices": [{"message": {"content": "<TRANSLATION>Hắn nhặt được linh thạch.</TRANSLATION><NEW_TERMS>灵石 -> linh thạch</NEW_TERMS>"}}]
            }).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        translate_chapter(
            text="他捡到灵石。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=False,
        )

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT target_term, approved FROM glossary_terms WHERE source_term = ?",
                ("灵石",),
            ).fetchone()

        assert row is not None
        assert row["target_term"] == "linh thạch"
        assert row["approved"] == 0

    def test_empty_postprocessed_chunk_is_retried(self, monkeypatch, tmp_path):
        import app.translation.ollama_client as ollama_mod
        from app.database.db import add_book, init_db

        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        db_path = tmp_path / "pipeline.db"
        init_db(db_path)
        add_book(db_path, "Test Book")
        monkeypatch.setattr("time.sleep", lambda _: None)

        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = Response()
            resp.status_code = 200
            content = (
                "<TRANSLATION>暗暗下定了决心</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"
                if call_count == 1
                else "<TRANSLATION>Bản dịch hợp lệ.</TRANSLATION><NEW_TERMS>NONE</NEW_TERMS>"
            )
            resp._content = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            return resp

        monkeypatch.setattr("requests.post", mock_post)

        result = translate_chapter(
            text="测试文本。",
            book_title="Test Book",
            chapter_title="Ch1",
            chapter_number=1,
            model="test-model",
            use_cache=False,
        )

        assert result == "Bản dịch hợp lệ."
        assert call_count == 2

    def test_new_terms_are_not_persisted_when_later_chunk_fails(self, monkeypatch, tmp_path):
        import requests
        import app.translation.ollama_client as ollama_mod
        from app.database.db import add_book, get_connection, init_db

        monkeypatch.setattr(ollama_mod.settings, "data_dir", tmp_path)
        db_path = tmp_path / "pipeline.db"
        init_db(db_path)
        add_book(db_path, "Test Book")
        monkeypatch.setattr("time.sleep", lambda _: None)

        call_count = 0

        def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = Response()
                resp.status_code = 200
                resp._content = json.dumps({
                    "choices": [{"message": {"content": "<TRANSLATION>Đoạn một.</TRANSLATION><NEW_TERMS>灵石 -> linh thạch</NEW_TERMS>"}}]
                }).encode()
                return resp
            raise requests.ConnectionError("Ollama not reachable")

        monkeypatch.setattr("requests.post", mock_post)

        with pytest.raises(Exception):
            translate_chapter(
                text="第一段。\n\n第二段。",
                book_title="Test Book",
                chapter_title="Ch1",
                chapter_number=1,
                model="test-model",
                chunk_size=5,
                use_cache=False,
            )

        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM glossary_terms WHERE source_term = ?",
                ("灵石",),
            ).fetchone()

        assert row is None
