from __future__ import annotations

import argparse

from app.config import settings
from app.database.db import init_db, list_chapters
from app.services.tts.tts_pipeline import TTSPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local Vietnamese TTS for a book.")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--format", choices=("mp3", "m4b"), default="m4b")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    init_db(settings.db_path)
    pipeline = TTSPipeline(settings.db_path, settings.resolved_data_dir)
    chapters = sorted(list_chapters(settings.db_path, args.book_id), key=lambda item: int(item.get("chapter_number") or 0))
    generated = 0
    for chapter in chapters:
        if args.limit and generated >= args.limit:
            break
        if not chapter.get("translated_text_path"):
            continue
        report = pipeline.generate_chapter(book_id=args.book_id, chapter_id=int(chapter["id"]))
        print(f"chapter {chapter['chapter_number']}: {report.status}")
        if report.status != "completed":
            raise SystemExit(1)
        generated += 1

    if args.format == "m4b":
        output = pipeline.generate_book_m4b(args.book_id)
        print(output)


if __name__ == "__main__":
    main()
