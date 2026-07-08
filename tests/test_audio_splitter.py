from __future__ import annotations

from app.audio.audio_splitter import split_text_for_tts


def test_split_text_for_tts_short_text_returns_single_chunk():
    text = "Đây là một câu ngắn."
    chunks = split_text_for_tts(text, max_chars=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_text_for_tts_long_text_splits_at_sentence_boundary():
    # Create sentences that are each under max_chars but together exceed max_chars
    # Each sentence ~100 chars, max_chars=200 -> first chunk gets sentence1, second gets sentence2, third gets sentence3
    sent1 = "Câu đầu tiên." * 8   # ~112 chars
    sent2 = "Câu thứ hai." * 8    # ~112 chars
    sent3 = "Câu thứ ba." * 8     # ~112 chars
    text = f"{sent1} {sent2} {sent3}"
    chunks = split_text_for_tts(text, max_chars=200)
    # Should split into at least 2 chunks
    assert len(chunks) >= 2
    # First chunk should contain sent1
    assert sent1 in chunks[0]
    # Last chunk should contain sent3
    assert sent3 in chunks[-1]
    # Each chunk should be <= max_chars (or slightly more due to joining space)
    for chunk in chunks:
        assert len(chunk) <= 200 + 5


def test_split_text_for_tts_empty_text():
    assert split_text_for_tts("", max_chars=200) == []


def test_split_text_for_tts_whitespace_only():
    # The function normalizes whitespace, so a string of spaces becomes empty string
    assert split_text_for_tts("   ", max_chars=200) == []


def test_split_text_for_tts_many_short_sentences_split():
    text = "Câu rất dài. " * 30
    chunks = split_text_for_tts(text, max_chars=200)
    assert len(chunks) == 2
    assert all(chunk.endswith(".") for chunk in chunks)
    assert "Câu rất dài." in chunks[0]
    assert "Câu rất dài." in chunks[1]
