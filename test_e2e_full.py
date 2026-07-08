#!/usr/bin/env python3
"""Full E2E test with complete chapter text."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.translation.ollama_client import translate_chapter


__test__ = False


def main() -> None:
    chapter_text = Path("test_e2e_raw.txt").read_text(encoding="utf-8")
    print(f"Input: {len(chapter_text)} characters")

    translated = translate_chapter(
        text=chapter_text,
        book_title="永夜",
        chapter_title="第一章 永夜",
        chapter_number=1,
        model=settings.ollama_model,
        host=settings.ollama_host,
        temperature=settings.ollama_temperature,
        chunk_size=settings.ollama_chunk_size,
    )

    print(f"Output: {len(translated)} characters")
    print(f"Ratio: {len(translated)/len(chapter_text):.2f}x")

    Path("test_e2e_full_chapter.md").write_text(f"""# Full Chapter Translation Test

**Book:** 永夜
**Chapter:** 1 - 第一章 永夜
**Input:** {len(chapter_text)} characters (raw Chinese)
**Output:** {len(translated)} characters (Vietnamese)
**Ratio:** {len(translated)/len(chapter_text):.2f}x

---

## Vietnamese Translation

{translated}
""", encoding="utf-8")

    print("Saved to test_e2e_full_chapter.md")
    print("\n=== FIRST 500 CHARS ===")
    print(translated[:500])
    print("\n=== LAST 500 CHARS ===")
    print(translated[-500:] if len(translated) > 500 else translated)


if __name__ == "__main__":
    main()
