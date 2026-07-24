#!/usr/bin/env python3
"""Publish a strict recovery receipt without embedding operational paths."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.recovery_receipts import publish_recovery_receipt


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
    publish_recovery_receipt(
        output,
        archive_hash_id=archive_hash_id,
        validation_counts=validation_counts,
        producer_version=producer_version,
        completed_at=(completed_at or datetime.now(timezone.utc)).astimezone(timezone.utc),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--archive-hash-id", required=True)
    parser.add_argument("--producer-version", required=True)
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
