from __future__ import annotations

from app.translation.idiom_correction import post_process_with_idioms


def test_post_process_replaces_common_chinese_idiom_leaks() -> None:
    assert post_process_with_idioms("Đúng là 一举两得.") == "Đúng là một công đôi việc."


def test_post_process_replaces_common_poetry_line_leaks() -> None:
    assert (
        post_process_with_idioms("Hắn khẽ ngâm 山重水复疑无路，柳暗花明又一村.")
        == "Hắn khẽ ngâm núi sông trùng điệp ngỡ không lối, liễu rậm hoa tươi lại thấy thôn."
    )


def test_post_process_uses_styleguide_forbidden_translation_rules() -> None:
    assert (
        post_process_with_idioms("Chủ nhà nhận được một vạn tích phân sau khi trói định thành công.")
        == "Ký chủ nhận được một vạn điểm tích lũy sau khi liên kết thành công."
    )


def test_post_process_normalizes_system_notification_terms_and_format() -> None:
    assert (
        post_process_with_idioms(
            "Đinh! Phát hiện ký chủ hoàn thành ẩn vụ, ban thưởng một vạn tích phân, có nhận hay không?"
        )
        == "[Đinh! Phát hiện ký chủ hoàn thành nhiệm vụ ẩn.]\n"
        "[Phần thưởng: một vạn điểm tích lũy.]\n"
        "[Có nhận không?]"
    )


def test_post_process_normalizes_split_dinh_prefix_system_notification() -> None:
    assert (
        post_process_with_idioms(
            "[Đinh!] Phát hiện ký chủ hoàn thành nhiệm vụ ẩn, ban thưởng một vạn điểm tích lũy, có lĩnh không?"
        )
        == "[Đinh! Phát hiện ký chủ hoàn thành nhiệm vụ ẩn.]\n"
        "[Phần thưởng: một vạn điểm tích lũy.]\n"
        "[Có nhận không?]"
    )


def test_post_process_repairs_common_vietnamese_spacing_artifacts() -> None:
    assert post_process_with_idioms("Hắn cầ u thấ y khô ng đượ c.") == "Hắn cầu thấy không được."


def test_post_process_splits_glued_chapter_heading_and_dedupes_title_prefix() -> None:
    assert (
        post_process_with_idioms(
            "Chương 1: Yên Vũ Tòa Thành Nhỏtòa thành nhỏ\n\n"
            "Lý Thanh đứng bên cầu cũ, nhìn thấy đèn đuốc xa xa."
        )
        == "Chương 1: Yên Vũ Tòa Thành Nhỏ\n\n"
        "Lý Thanh đứng bên cầu cũ, nhìn thấy đèn đuốc xa xa."
    )


def test_post_process_does_not_insert_spaces_inside_urls_or_numbers() -> None:
    assert (
        post_process_with_idioms("URL: https://example.com/a?x=1.5. Hắn nói:được.")
        == "URL: https://example.com/a?x=1.5. Hắn nói:được."
    )
