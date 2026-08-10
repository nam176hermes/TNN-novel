"""Dispatch operational alerts from a fresh runtime snapshot."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

from app.config import settings
from app.mobile_api.services.operational_metrics_service import OperationalMetricsService
from app.services.operational_alert_delivery import (
    AlertDeliveryConfig,
    OperationalAlertDispatcher,
    SUPPORTED_ALERT_CLASSES,
)


_ENVIRONMENT_NAMES = (
    "NOVEL_ALERT_WEBHOOK_URL",
    "NOVEL_ALERT_WEBHOOK_BEARER_TOKEN",
    "NOVEL_ALERT_TIMEOUT_SECONDS",
    "NOVEL_ALERT_MAX_ATTEMPTS",
)
_RECEIPT_STATUSES = frozenset({"delivered", "failed", "resolved"})


def _open_database_guard(database_path: Path) -> tuple[int, tuple[int, int]]:
    database_path = Path(database_path)
    if (
        not database_path.is_absolute()
        or ".." in database_path.parts
        or database_path == Path(database_path.anchor)
    ):
        raise ValueError("Operational database path is unsafe")
    descriptor = os.open(
        database_path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        descriptor_metadata = os.fstat(descriptor)
        path_metadata = os.stat(database_path, follow_symlinks=False)
        identity = (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
        if not stat.S_ISREG(descriptor_metadata.st_mode) or identity != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise ValueError("Operational database path is unsafe")
        return descriptor, identity
    except BaseException:
        os.close(descriptor)
        raise


def _verify_database_guard(
    database_path: Path,
    descriptor: int,
    identity: tuple[int, int],
) -> None:
    descriptor_metadata = os.fstat(descriptor)
    path_metadata = os.stat(database_path, follow_symlinks=False)
    if (
        not stat.S_ISREG(descriptor_metadata.st_mode)
        or identity != (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
        or identity != (path_metadata.st_dev, path_metadata.st_ino)
    ):
        raise ValueError("Operational database changed during snapshot")


def _configuration_from_environment() -> AlertDeliveryConfig:
    values = {name: os.getenv(name, "") for name in _ENVIRONMENT_NAMES}
    if not values["NOVEL_ALERT_WEBHOOK_URL"].strip():
        raise ValueError("Missing operational alert webhook configuration")
    return AlertDeliveryConfig(
        webhook_url=values["NOVEL_ALERT_WEBHOOK_URL"],
        bearer_token=values["NOVEL_ALERT_WEBHOOK_BEARER_TOKEN"],
        timeout_seconds=values["NOVEL_ALERT_TIMEOUT_SECONDS"] or 5.0,
        max_attempts=values["NOVEL_ALERT_MAX_ATTEMPTS"] or 3,
    )


def main() -> int:
    try:
        config = _configuration_from_environment()
    except (TypeError, ValueError):
        print("status=configuration_error", file=sys.stderr)
        return 2

    try:
        data_dir = settings.resolved_data_dir
        database_path = settings.db_path
        database_descriptor, database_identity = _open_database_guard(database_path)
        try:
            service = OperationalMetricsService(database_path, data_dir, read_only=True)
            snapshot = service.snapshot(use_cache=False)
            _verify_database_guard(
                database_path,
                database_descriptor,
                database_identity,
            )
        finally:
            os.close(database_descriptor)
        dispatcher = OperationalAlertDispatcher(
            config,
            receipt_dir=data_dir / "logs" / "runtime",
        )
        receipts = dispatcher.dispatch(snapshot)
        by_class = {
            receipt.alert_class: receipt
            for receipt in receipts
            if receipt.alert_class in SUPPORTED_ALERT_CLASSES
            and receipt.status in _RECEIPT_STATUSES
        }
        if set(by_class) != set(SUPPORTED_ALERT_CLASSES):
            raise ValueError("Operational alert results are incomplete")
    except Exception:
        print("status=error", file=sys.stderr)
        return 1

    failed = False
    for alert_class in SUPPORTED_ALERT_CLASSES:
        status = by_class[alert_class].status
        print(f"class={alert_class} status={status}")
        failed = failed or status == "failed"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
