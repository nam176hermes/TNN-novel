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


def test_chunker_splits_very_long_paragraph_without_empty_chunks() -> None:
    text = (
        "Hắn bước qua động phủ, nhìn lên bầu trời đầy mây xám và chậm rãi kể lại toàn bộ chuyện cũ, "
        "từ lúc rời tông môn cho tới khi gặp lại cố nhân trong trận mưa rất dài, rất lạnh và đầy tiếng gió. "
        "Nàng đứng yên lặng nghe hết, rồi chỉ khẽ đáp rằng mọi việc vẫn chưa kết thúc."
    )

    chunks = chunk_text(text, chapter_id=11, max_chars=90, max_sentences=2)

    assert len(chunks) >= 2
    assert all(chunk.text.strip() for chunk in chunks)
    assert all(chunk.normalized_text.strip() for chunk in chunks)
    assert all(chunk.end_char > chunk.start_char for chunk in chunks)


def test_chunker_drops_blank_input() -> None:
    assert chunk_text("   \n\n   ", chapter_id=3) == []
