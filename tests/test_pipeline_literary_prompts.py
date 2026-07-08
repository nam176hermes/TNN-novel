from __future__ import annotations

import sys
import types

if "edge_tts" not in sys.modules:
    edge_tts_stub = types.ModuleType("edge_tts")
    edge_tts_stub.Communicate = object
    sys.modules["edge_tts"] = edge_tts_stub

from app.mobile_api.services.pipeline_service import _build_chapter_polish_prompt


def test_chapter_polish_prompt_includes_literary_phrase_guidance_for_source() -> None:
    prompt = _build_chapter_polish_prompt(
        source_text="他吟道：举头望明月，低头思故乡。",
        rough_translation="Hắn ngâm: ngẩng đầu trông trăng sáng, cúi đầu nhớ quê nhà.",
        book_title="Test",
        chapter_title="Ch1",
        chapter_number=1,
    )

    assert "Literary phrase guide:" in prompt
    assert "Thơ, thành ngữ, tục ngữ, đối liên, điển cố" in prompt
    assert "举头望明月，低头思故乡 -> ngẩng đầu nhìn trăng sáng, cúi đầu nhớ cố hương" in prompt
