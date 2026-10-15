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


def test_numeric_punctuation_is_not_split_before_normalizing() -> None:
    text = normalize_text("Có 1.000 viên, nặng 3,14 kg; ngày 02/10/2026. Mã 007, bản v1.2.3.", backend="rule_based").text
    assert "một nghìn viên" in text
    assert "ba phẩy một bốn kg" in text
    assert "ngày hai tháng mười năm hai nghìn không trăm hai mươi sáu" in text
    assert "Mã không không bảy" in text
    assert "v1.2.3" in text


def test_large_grouped_numbers_preserve_all_digits_and_negative_codes():
    text = normalize_text("Mã -007; số 1.000.000.000.001.", backend="rule_based").text
    assert "âm không không bảy" in text
    assert "một không không không không không không không không không không không một" in text
