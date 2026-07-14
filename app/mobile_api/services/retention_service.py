from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Literal

from app.database.auth_repository import prune_auth_records
from app.database.connection import get_connection
from app.database.operations_repository import (
    RetentionPolicy,
    prune_operational_events,
    record_operational_event,
)
from app.mobile_api.config import MobileAPISettings, mobile_settings


logger = logging.getLogger(__name__)

RETENTION_TABLE_LABELS = (
    "auth_sessions",
    "auth_login_failures",
    "operational_events",
)


@dataclass(frozen=True)
class RetentionSummary:
    last_run_at: str
    deleted_counts: dict[str, int]
    result: Literal["completed", "skipped"]

    def to_status(self) -> dict[str, Any]:
        return {
            "last_run_at": self.last_run_at,
            "deleted_counts": dict(self.deleted_counts),
            "result": self.result,
        }


def _utcnow_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_counts() -> dict[str, int]:
    return {label: 0 for label in RETENTION_TABLE_LABELS}


def _count_retention_rows(db_path: Path) -> dict[str, int]:
    counts = _empty_counts()
    with get_connection(db_path) as conn:
        for table in RETENTION_TABLE_LABELS:
            row = conn.execute(f"SELECT COUNT(*) AS row_count FROM {table}").fetchone()
            counts[table] = int(row["row_count"] if row else 0)
    return counts


def _is_sqlite_contention(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(
        marker in str(exc).lower() for marker in ("locked", "busy")
    )


async def _default_yield_control() -> None:
    await asyncio.sleep(0)


class RetentionService:
    def __init__(
        self,
        db_path: Path,
        *,
        settings: MobileAPISettings = mobile_settings,
        yield_control: Callable[[], Awaitable[None]] = _default_yield_control,
    ) -> None:
        self.db_path = Path(db_path)
        self.settings = settings
        self._yield_control = yield_control
        self._last_summary: RetentionSummary | None = None
        self._session_policy = RetentionPolicy(
            max_age_days=settings.auth_session_retention_days,
            max_rows=settings.auth_session_retention_max_rows,
        )
        self._login_failure_policy = RetentionPolicy(
            max_age_days=settings.auth_login_failure_retention_days,
            max_rows=settings.auth_login_failure_retention_max_rows,
        )
        self._operational_event_policy = RetentionPolicy(
            max_age_days=settings.operational_event_retention_days,
            max_rows=settings.operational_event_retention_max_rows,
        )

    @property
    def last_summary(self) -> RetentionSummary | None:
        return self._last_summary

    async def run_once(self) -> RetentionSummary:
        deleted_counts = _empty_counts()
        batch_size = self.settings.operational_retention_batch_size

        try:
            while True:
                deleted = await asyncio.to_thread(
                    prune_auth_records,
                    self.db_path,
                    session_policy=self._session_policy,
                    login_failure_policy=self._login_failure_policy,
                    batch_size=batch_size,
                )
                deleted_counts["auth_sessions"] += int(deleted.get("auth_sessions", 0))
                deleted_counts["auth_login_failures"] += int(
                    deleted.get("auth_login_failures", 0)
                )
                if sum(deleted.values()) < batch_size:
                    break
                await self._yield_control()

            await self._yield_control()

            while True:
                deleted = await asyncio.to_thread(
                    prune_operational_events,
                    self.db_path,
                    policy=self._operational_event_policy,
                    batch_size=batch_size,
                )
                deleted_counts["operational_events"] += int(deleted)
                if deleted < batch_size:
                    break
                await self._yield_control()

            if sum(deleted_counts.values()) > 0:
                await asyncio.to_thread(
                    record_operational_event,
                    self.db_path,
                    event_type="operational_retention",
                    severity="info",
                    source="retention",
                    message="Operational retention completed",
                    details=dict(deleted_counts),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not _is_sqlite_contention(exc):
                raise
            logger.info("Retention maintenance skipped because the database is busy")
            summary = RetentionSummary(
                last_run_at=_utcnow_text(),
                deleted_counts=deleted_counts,
                result="skipped",
            )
            self._last_summary = summary
            return summary

        summary = RetentionSummary(
            last_run_at=_utcnow_text(),
            deleted_counts=deleted_counts,
            result="completed",
        )
        self._last_summary = summary
        return summary

    async def get_status(self, *, db_path: Path | None = None) -> dict[str, Any]:
        try:
            table_counts = await asyncio.to_thread(
                _count_retention_rows,
                Path(db_path) if db_path is not None else self.db_path,
            )
        except sqlite3.Error:
            table_counts = _empty_counts()
        return {
            "table_counts": table_counts,
            "last_run": self._last_summary.to_status() if self._last_summary else None,
        }


async def run_retention_loop(
    service: RetentionService,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    while not stop_event.is_set():
        try:
            await service.run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Retention maintenance failed; retrying at the next interval")

        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
