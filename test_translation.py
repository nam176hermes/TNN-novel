#!/usr/bin/env python3
"""
Test script to translate a sample Chinese text using the improved novel_pipeline.
Outputs the translation to a markdown file.
"""

import os
import tempfile
from pathlib import Path
import sys

# Add the novel_pipeline root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.database.db import get_connection, init_db, add_book, add_chapter, update_chapter_paths
from app.ingestion.importers import import_file
from app.translation.ollama_client import translate_chapter, TranslationError
from app.config import settings as pipeline_settings
from app.database.db import get_book_by_title, get_chapter

def main():
    # Ensure data directory exists
    data_dir = Path.cwd() / pipeline_settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    # Initialize database if needed
    db_path = data_dir / "pipeline.db"
    with get_connection(db_path) as conn:
        conn.execute("SELECT 1")  # just to check
    # Note: init_db is called in get_connection? Actually, we have to call it explicitly if tables missing.
    # We'll rely on the fact that the database is already initialized from previous runs.

    # Create a unique book title to avoid conflicts
    import time
    book_title = f"Test Book {int(time.time())}"
    chapter_number = 1
    chapter_title = "Test Chapter"
    # Sample Chinese text: a mix of common phrases and names that should benefit from our improvements
    chinese_text = """
韩立修炼多年，终于筑基成功。他走出石室，看到师兄正在等待。
“师兄，你怎么说我也要快了一点？”韩立笑着说道。
师兄淡淡道：“修炼不是比赛，急躁会走火入魔。”
韩立点了点头，心里却暗暗下定了决心：一定要比师兄强！
"""

    # Write the raw text to a temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(chinese_text)
        raw_path = Path(f.name)

    try:
        # Import the chapter (this will create the book if it doesn't exist)
        safe_title = "".join(c if c.isalnum() or c in ".-_" else "_" for c in book_title)
        imported_path = import_file(book_title, chapter_number, chapter_title, raw_path)
        print(f"Imported chapter to: {imported_path}")

        # Get the book and chapter IDs
        book = get_book_by_title(db_path, book_title)
        if not book:
            raise Exception(f"Book '{book_title}' not found after import")
        book_id = book["id"]
        chapter = get_chapter(db_path, book_id, chapter_number)
        if not chapter:
            raise Exception(f"Chapter {chapter_number} not found in book '{book_title}'")

        # Translate the chapter
        print(f"Translating '{book_title}' chapter {chapter_number}...")
        translated_text = translate_chapter(
            text=chinese_text,
            book_title=book_title,
            chapter_title=chapter["title"],
            chapter_number=chapter_number,
            # Use default settings from config
        )

        # Save the translated text (the translate_chapter function already saves it via the pipeline?)
        # Actually, translate_chapter returns the text but does not save it.
        # The save is done in the translate_cmd or daily_cmd functions.
        # We'll save it manually for the test.
        safe_book = "".join(c if c.isalnum() or c in ".-_" else "_" for c in book_title)
        translated_path = data_dir / "translated" / safe_book / f"chapter_{chapter_number:04d}.txt"
        translated_path.parent.mkdir(parents=True, exist_ok=True)
        translated_path.write_text(translated_text, encoding="utf-8")
        print(f"Saved translation to: {translated_path}")

        # Also output as markdown
        markdown_path = Path("test_translation_result.md")
        markdown_content = f"# Translation Test\n\n**Book:** {book_title}\n**Chapter:** {chapter_number} - {chapter_title}\n\n## Original Chinese:\n\n{chinese_text}\n\n## Vietnamese Translation:\n\n{translated_text}\n"
        markdown_path.write_text(markdown_content, encoding="utf-8")
        print(f"Markdown result saved to: {markdown_path}")

        # Print a preview
        print("\n--- Translation Preview ---")
        print(translated_text[:500] + ("..." if len(translated_text) > 500 else ""))
        print("---------------------------")

    finally:
        # Clean up the temporary raw file
        os.unlink(raw_path)

if __name__ == "__main__":
    main()