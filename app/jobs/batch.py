from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from dotenv import load_dotenv

from app.config import PROJECT_ROOT, settings
from app.database.db import init_db
from app.mobile_api.services.job_service import JobService, get_shared_job_tracker
from app.mobile_api.services.pipeline_service import PipelineService


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "canceled", "interrupted"}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local batch jobs without a web login session.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate = subparsers.add_parser(
        "translate",
        help="Translate untranslated chapters for a book.",
    )
    translate.add_argument("--book-id", type=int, required=True)
    translate.add_argument("--limit", type=_positive_int, default=500)
    translate.add_argument("--preset-id", default="balanced")
    translate.add_argument("--style-profile-id", default="")
    translate.add_argument("--chunk-size", type=_positive_int, default=None)
    translate.add_argument("--poll-interval", type=float, default=1.0)

    tts = subparsers.add_parser(
        "tts",
        help="Generate audio for translated chapters that do not have audio.",
    )
    tts.add_argument("--book-id", type=int, required=True)
    tts.add_argument("--limit", type=_positive_int, default=200)
    tts.add_argument("--voice", default="")
    tts.add_argument("--rate", default="-5%")
    tts.add_argument("--volume", default="+0%")
    tts.add_argument("--poll-interval", type=float, default=1.0)

    return parser


def _service() -> JobService:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    init_db(settings.db_path)
    return JobService(PipelineService(), tracker=get_shared_job_tracker(settings.db_path))


async def _wait_for_job(service: JobService, job_id: str, poll_interval: float) -> dict:
    last_line = ""
    while True:
        status = service.get_job_status(job_id)
        if status is None:
            raise RuntimeError(f"Job {job_id} disappeared before completion")

        line = (
            f"{status.get('status', 'unknown')} "
            f"{status.get('progress', 0)}/{status.get('total', 0)} "
            f"{status.get('message') or ''}"
        ).strip()
        if line != last_line:
            print(line)
            last_line = line

        if str(status.get("status") or "").lower() in TERMINAL_STATUSES:
            return status

        await asyncio.sleep(max(0.1, poll_interval))


async def run(args: argparse.Namespace) -> int:
    service = _service()

    if args.command == "translate":
        job_id = service.start_translate_job(
            book_id=args.book_id,
            chapter_ids=[],
            limit=args.limit,
            preset_id=args.preset_id,
            style_profile_id=args.style_profile_id or None,
            chunk_size=args.chunk_size,
        )
    elif args.command == "tts":
        job_id = service.start_tts_job(
            book_id=args.book_id,
            chapter_ids=[],
            limit=args.limit,
            voice=args.voice or None,
            rate=args.rate,
            volume=args.volume,
        )
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    print(f"job_id={job_id}")
    status = await _wait_for_job(service, job_id, args.poll_interval)
    if str(status.get("status") or "").lower() == "completed":
        return 0

    error = status.get("error") or status.get("message") or "Job did not complete"
    print(f"error={error}")
    return 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
