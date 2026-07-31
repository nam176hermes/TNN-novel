#!/usr/bin/env python3
"""Publish a strict recovery receipt without embedding operational paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.recovery_receipts import publish_recovery_receipt


_COMPLETED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
_COMPLETED_AT_LENGTH = 25
_MAX_FUTURE_SKEW = timedelta(seconds=300)


def _validated_completed_at(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("completion timestamp must be UTC")
    normalized = value.astimezone(timezone.utc)
    if normalized > datetime.now(timezone.utc) + _MAX_FUTURE_SKEW:
        raise ValueError("completion timestamp exceeds allowed clock skew")
    return normalized


def _completed_at_argument(value: str) -> datetime:
    if len(value) != _COMPLETED_AT_LENGTH:
        raise argparse.ArgumentTypeError("must be a bounded canonical UTC timestamp")
    try:
        parsed = datetime.strptime(value, _COMPLETED_AT_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a bounded canonical UTC timestamp") from None
    if value != parsed.isoformat():
        raise argparse.ArgumentTypeError("must be a bounded canonical UTC timestamp")
    try:
        return _validated_completed_at(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def record_success(
    output: Path,
    *,
    archive_hash_id: str,
    validation_counts: dict[str, int],
    producer_version: str,
    completed_at: datetime | None = None,
) -> None:
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("restore-drill status path must be absolute")
    timestamp = datetime.now(timezone.utc) if completed_at is None else _validated_completed_at(completed_at)
    publish_recovery_receipt(
        output,
        archive_hash_id=archive_hash_id,
        validation_counts=validation_counts,
        producer_version=producer_version,
        completed_at=timestamp,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--archive-hash-id", required=True)
    parser.add_argument("--producer-version", required=True)
    parser.add_argument("--completed-at", type=_completed_at_argument, metavar="UTC_TIMESTAMP")
    parser.add_argument("--validation-count", action="append", required=True, metavar="KEY=INTEGER")
    args = parser.parse_args()
    counts: dict[str, int] = {}
    for item in args.validation_count:
        key, separator, value = item.partition("=")
        if not separator:
            parser.error("--validation-count must use KEY=INTEGER")
        try:
            counts[key] = int(value)
        except ValueError:
            parser.error("--validation-count value must be an integer")
    record_success(
        args.output,
        archive_hash_id=args.archive_hash_id,
        validation_counts=counts,
        producer_version=args.producer_version,
        completed_at=args.completed_at,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
