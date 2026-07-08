from app.services.tts.chunker import chunk_text


def test_chunker_keeps_stable_metadata_and_limits_size() -> None:
    text = "Chương một. Đây là câu đầu. Đây là câu hai. Đây là câu ba. Đây là câu bốn."

    chunks = chunk_text(text, chapter_id=7, max_chars=35, max_sentences=2)

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.chapter_id == 7 for chunk in chunks)
    assert all(len(chunk.normalized_text) <= 45 for chunk in chunks)
    assert "".join(text[chunk.start_char:chunk.end_char] for chunk in chunks).replace(" ", "") in text.replace(" ", "")


def test_chunker_avoids_splitting_balanced_dialogue_when_possible() -> None:
    text = '"Đừng đi. Ta chưa nói xong," hắn khẽ nói. Sau đó trời sáng. Một tiếng chuông vang lên.'

    chunks = chunk_text(text, max_chars=70, max_sentences=2)

    assert chunks
    assert any('"Đừng đi. Ta chưa nói xong," hắn khẽ nói.' in chunk.text for chunk in chunks)
