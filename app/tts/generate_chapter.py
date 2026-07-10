from __future__ import annotations

import argparse

from app.config import settings
from app.database.db import init_db
from app.services.tts.tts_pipeline import TTSPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate local Vietnamese TTS for one chapter.")
    parser.add_argument("--book-id", type=int, required=True)
    parser.add_argument("--chapter-id", type=int, required=True)
    parser.add_argument("--job-id", default="")
    args = parser.parse_args()

    init_db(settings.db_path)
    report = TTSPipeline(settings.db_path, settings.resolved_data_dir).generate_chapter(
        book_id=args.book_id,
        chapter_id=args.chapter_id,
        job_id=args.job_id,
    )
    print(f"{report.status}: {report.output_mp3_path or report.error_message}")
    if report.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
