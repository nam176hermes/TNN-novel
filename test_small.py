#!/usr/bin/env python3
"""Quick test with first paragraph only."""

import sys
sys.path.insert(0, '.')

from app.config import settings
from app.translation.ollama_client import translate_chapter

__test__ = False


def main() -> None:
    para1 = """第一章 永夜

那一天太阳落下再也没有升起……

永夜，天地漆黑，似不可测的深渊要吞噬一切。白昼早已沦为过往，成为传说。
"""

    print(f"Input: {len(para1)} characters")

    translated = translate_chapter(
        text=para1,
        book_title="永夜",
        chapter_title="第一章 永夜",
        chapter_number=1,
        model=settings.ollama_model,
        host=settings.ollama_host,
        temperature=settings.ollama_temperature,
        chunk_size=settings.ollama_chunk_size,
    )

    print(f"Output: {len(translated)} characters")
    print("Translation:")
    print(translated)


if __name__ == "__main__":
    main()
