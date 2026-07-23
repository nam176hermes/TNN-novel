#!/usr/bin/env python3
"""Atomically publish the last successful isolated restore-drill timestamp."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def record_success(output: Path, *, completed_at: datetime | None = None) -> None:
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("restore-drill status path must be absolute")
    timestamp = (completed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {"status": "passed", "completed_at": timestamp.isoformat()}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, output)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    record_success(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
