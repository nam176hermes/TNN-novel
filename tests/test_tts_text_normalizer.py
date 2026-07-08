from app.services.tts.text_normalizer import normalize_text, number_to_vietnamese


def test_rule_based_normalizer_cleans_markup_and_reads_chapter_number() -> None:
    result = normalize_text("<p>**Chương 123** 😄: hắn có 42 linh thạch.</p>", backend="missing")

    assert result.backend == "rule_based"
    assert "Chương một trăm hai mươi ba" in result.text
    assert "bốn mươi hai" in result.text
    assert "<p>" not in result.text
    assert "😄" not in result.text


def test_number_to_vietnamese_handles_common_values() -> None:
    assert number_to_vietnamese(0) == "không"
    assert number_to_vietnamese(105) == "một trăm lẻ năm"
    assert number_to_vietnamese(1234) == "một nghìn hai trăm ba mươi bốn"
