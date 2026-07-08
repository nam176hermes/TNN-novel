#!/usr/bin/env python3
"""E2E test with full chapter text."""

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

    Path("test_e2e_translated.md").write_text(f"""# E2E Test Result

**Input:** {len(chapter_text)} characters (full chapter)

**Output:** {len(translated)} characters

## Vietnamese Translation

{translated}
""", encoding="utf-8")

    print("Saved to test_e2e_translated.md")


if __name__ == "__main__":
    main()
