from __future__ import annotations

import argparse

from app.config import settings
from app.database.db import init_db
from app.services.tts.tts_pipeline import TTSPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry failed chunks for a TTS job.")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    init_db(settings.db_path)
    report = TTSPipeline(settings.db_path, settings.resolved_data_dir).retry_failed_chunks(args.job_id)
    print(f"{report.status}: {report.output_mp3_path or report.error_message}")
    if report.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
