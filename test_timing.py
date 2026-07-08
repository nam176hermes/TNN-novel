#!/usr/bin/env python3
"""Time each chunk to see performance."""

import sys, time
from pathlib import Path
sys.path.insert(0, '.')

from app.translation.ollama_client import translate_chapter


__test__ = False


def main() -> None:
    text = Path("test_e2e_raw.txt").read_text(encoding="utf-8")
    print(f"Input: {len(text)} chars")
    t0 = time.time()

    translated = translate_chapter(
        text=text,
        book_title="永夜",
        chapter_title="第一章 永夜",
        chapter_number=1,
        chunk_size=500,
    )

    elapsed = time.time() - t0
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"Output: {len(translated)} chars")
    Path("test_e2e_500.md").write_text(f"# Test Result\n\n{translated}", encoding="utf-8")
    print("=== START ===")
    print(translated[:300])
    print()
    print("=== MIDDLE ===")
    mid = len(translated) // 2
    print(translated[mid - 150:mid + 150])
    print()
    print("=== END ===")
    print(translated[-300:])


if __name__ == "__main__":
    main()
