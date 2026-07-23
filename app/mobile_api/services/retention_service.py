from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Literal

from app.database.auth_repository import get_auth_session_retention_report, prune_auth_records
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
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    error_code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(error_code, int) and error_code & 0xFF in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }:
        return True
    message = str(exc).strip().lower()
    return any(
        marker in message
        for marker in (
            "database is busy",
            "database is locked",
            "database table is locked",
            "database schema is locked",
        )
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
        self._pending_audit_counts = _empty_counts()
        self._active_worker_task: asyncio.Task[Any] | None = None
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

    @staticmethod
    def _has_deletions(counts: dict[str, int]) -> bool:
        return sum(counts.values()) > 0

    def _add_pending_audit(self, counts: dict[str, int]) -> None:
        for label in RETENTION_TABLE_LABELS:
            self._pending_audit_counts[label] += int(counts.get(label, 0))

    async def _run_sync_call(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        on_completed: Callable[[Any], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        if self._active_worker_task is not None:
            raise RuntimeError("Retention repository worker already active")
        worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self._active_worker_task = worker
        callback_called = False

        def publish(result: Any) -> None:
            nonlocal callback_called
            if on_completed is not None and not callback_called:
                on_completed(result)
            callback_called = True

        try:
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    result = await asyncio.shield(worker)
                except Exception:
                    pass
                else:
                    publish(result)
                raise
            publish(result)
            return result
        finally:
            if worker.done():
                self._active_worker_task = None

    async def _flush_pending_audit(self) -> None:
        if not self._has_deletions(self._pending_audit_counts):
            return
        pending = dict(self._pending_audit_counts)

        def clear_pending(_: Any) -> None:
            for label in RETENTION_TABLE_LABELS:
                self._pending_audit_counts[label] -= pending[label]

        await self._run_sync_call(
            record_operational_event,
            self.db_path,
            event_type="operational_retention",
            severity="info",
            source="retention",
            message="Operational retention completed",
            details=pending,
            on_completed=clear_pending,
        )

    async def run_once(
        self,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> RetentionSummary:
        deleted_counts = _empty_counts()
        batch_size = self.settings.operational_retention_batch_size
        audit_completed = False

        def stopped() -> bool:
            return stop_event is not None and stop_event.is_set()

        def skipped_summary() -> RetentionSummary:
            summary = RetentionSummary(
                last_run_at=_utcnow_text(),
                deleted_counts=dict(deleted_counts),
                result="skipped",
            )
            self._last_summary = summary
            return summary

        try:
            await self._flush_pending_audit()
            if stopped():
                return skipped_summary()

            initial_counts = await self._run_sync_call(_count_retention_rows, self.db_path)
            auth_budget = int(initial_counts["auth_sessions"]) + int(
                initial_counts["auth_login_failures"]
            )
            event_budget = int(initial_counts["operational_events"])
            auth_processed = 0
            event_processed = 0

            while auth_processed < auth_budget:
                if stopped():
                    if self._has_deletions(deleted_counts):
                        self._add_pending_audit(deleted_counts)
                    return skipped_summary()
                current_batch_size = min(batch_size, auth_budget - auth_processed)

                def publish_auth(deleted: dict[str, int]) -> None:
                    nonlocal auth_processed
                    deleted_total = sum(int(value) for value in deleted.values())
                    deleted_counts["auth_sessions"] += int(deleted.get("auth_sessions", 0))
                    deleted_counts["auth_login_failures"] += int(
                        deleted.get("auth_login_failures", 0)
                    )
                    auth_processed += deleted_total

                deleted = await self._run_sync_call(
                    prune_auth_records,
                    self.db_path,
                    session_policy=self._session_policy,
                    login_failure_policy=self._login_failure_policy,
                    batch_size=current_batch_size,
                    on_completed=publish_auth,
                )
                if stopped():
                    self._add_pending_audit(deleted_counts)
                    return skipped_summary()
                if sum(deleted.values()) < current_batch_size:
                    break
                if auth_processed < auth_budget:
                    await self._yield_control()

            if event_budget > 0 and not stopped():
                await self._yield_control()

            while event_processed < event_budget:
                if stopped():
                    if self._has_deletions(deleted_counts):
                        self._add_pending_audit(deleted_counts)
                    return skipped_summary()
                current_batch_size = min(batch_size, event_budget - event_processed)

                def publish_events(deleted: int) -> None:
                    nonlocal event_processed
                    deleted_counts["operational_events"] += int(deleted)
                    event_processed += int(deleted)

                deleted = await self._run_sync_call(
                    prune_operational_events,
                    self.db_path,
                    policy=self._operational_event_policy,
                    batch_size=current_batch_size,
                    reserved_rows=1,
                    on_completed=publish_events,
                )
                if stopped():
                    self._add_pending_audit(deleted_counts)
                    return skipped_summary()
                if deleted < current_batch_size:
                    break
                if event_processed < event_budget:
                    await self._yield_control()

            if self._has_deletions(deleted_counts):
                def mark_audit_completed(_: Any) -> None:
                    nonlocal audit_completed
                    audit_completed = True

                await self._run_sync_call(
                    record_operational_event,
                    self.db_path,
                    event_type="operational_retention",
                    severity="info",
                    source="retention",
                    message="Operational retention completed",
                    details=dict(deleted_counts),
                    on_completed=mark_audit_completed,
                )
        except asyncio.CancelledError:
            if self._has_deletions(deleted_counts) and not audit_completed:
                self._add_pending_audit(deleted_counts)
            raise
        except Exception as exc:
            if self._has_deletions(deleted_counts) and not audit_completed:
                self._add_pending_audit(deleted_counts)
            if not _is_sqlite_contention(exc):
                raise
            logger.info("Retention maintenance skipped because the database is busy")
            return skipped_summary()

        summary = RetentionSummary(
            last_run_at=_utcnow_text(),
            deleted_counts=deleted_counts,
            result="completed",
        )
        self._last_summary = summary
        return summary

    async def get_status(self) -> dict[str, Any]:
        try:
            table_counts = await asyncio.to_thread(_count_retention_rows, self.db_path)
        except sqlite3.Error:
            table_counts = _empty_counts()
        try:
            auth_session_counts = await asyncio.to_thread(
                get_auth_session_retention_report,
                self.db_path,
                session_policy=self._session_policy,
            )
        except sqlite3.Error:
            auth_session_counts = {
                "total": 0,
                "active": 0,
                "expired": 0,
                "revoked": 0,
                "age_eligible": 0,
                "row_cap_eligible": 0,
                "would_remove": 0,
            }
        return {
            "table_counts": table_counts,
            "auth_session_counts": auth_session_counts,
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
            if isinstance(service, RetentionService):
                await service.run_once(stop_event=stop_event)
            else:
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
