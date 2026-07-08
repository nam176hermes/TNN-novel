from __future__ import annotations

from app.ingestion.chapter_cleaner import clean_chapter


def test_clean_chapter_removes_html_boilerplate():
    """Lines starting with HTML tags should be removed."""
    raw = (
        "<html>\n"
        "<div class=\"content\">\n"
        "第一章\n"
        "仙侠世界\n"
        "</div>\n"
        "</html>\n"
    )
    result = clean_chapter(raw)
    assert "第一章" in result
    assert "仙侠世界" in result
    assert "<html>" not in result
    assert "<div" not in result


def test_clean_chapter_collapses_blank_lines():
    """Multiple consecutive blank lines should collapse to one."""
    raw = "第一段\n\n\n\n第二段\n\n\n第三段"
    result = clean_chapter(raw)
    paragraphs = result.split("\n\n")
    assert len(paragraphs) == 3
    # No triple newlines anywhere
    assert "\n\n\n" not in result


def test_clean_chapter_removes_short_junk():
    """Lines under 4 chars without CJK should be removed."""
    raw = "第一章\n12\nabc\n!!!\n修真世界"
    result = clean_chapter(raw)
    assert "第一章" in result
    assert "修真世界" in result
    # "abc" is 3 chars ascii, no CJK - removed
    # "12" is 2 chars - removed
    # "!!!" is 3 chars - removed
    assert "12" not in result
    assert "!!!" not in result


def test_clean_chapter_preserves_normal_text():
    """Normal Chinese text should be preserved intact."""
    raw = (
        "张铁睁开双眼，发现自己躺在一间破旧的茅草屋里。\n"
        "他揉了揉眼睛，确信自己不是在梦中。"
    )
    result = clean_chapter(raw)
    assert "张铁睁开双眼" in result
    assert "破旧的茅草屋" in result


def test_clean_chapter_handles_mixed_content():
    """Mixed valid text and boilerplate/junk should keep only valid text."""
    raw = (
        "<script>var x=1;</script>\n"
        "第一章\n"
        "\n"
        "\n"
        "12\n"
        "修仙之路\n"
        "\n"
        "!!!\n"
        "<br>\n"
        "真元流转\n"
    )
    result = clean_chapter(raw)
    # Valid text present
    assert "第一章" in result
    assert "修仙之路" in result
    assert "真元流转" in result
    # Junk removed
    assert "<script>" not in result
    assert "12" not in result
    assert "!!!" not in result
    assert "<br>" not in result
    # Blank lines collapsed
    assert "\n\n\n" not in result
