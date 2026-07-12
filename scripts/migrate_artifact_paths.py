#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.storage.artifact_paths import (  # noqa: E402
    APPROVED_PATH_FIELDS,
    ArtifactClass,
    ArtifactResolution,
    PathField,
    ResolutionStatus,
    resolve_artifact_path,
)


MIGRATION_VERSION = "p0a-artifact-paths-v1"
SUMMARY_JSON = "artifact-path-migration-summary.json"
SUMMARY_MARKDOWN = "artifact-path-migration-summary.md"
ROLLBACK_JSON = "artifact-path-migration-rollback.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationOptions:
    db_path: Path
    old_root: Path
    new_root: Path
    report_dir: Path
    verify_files: bool = False
    allow_missing: bool = False
    apply: bool = False
    backup_confirmation: str = ""
    expected_db_sha256: str = ""
    rollback_sql_output: Path | None = None


@dataclass
class FieldCounts:
    table: str
    column: str
    record_count: int = 0
    old_root_match_count: int = 0
    null_blank_count: int = 0
    already_current_count: int = 0
    missing_file_count_before_remap: int = 0
    existing_file_count_after_remap: int = 0
    remappable_count: int = 0
    unresolved_count: int = 0
    containment_failure_count: int = 0
    path_kind: str = "file"
    migrate: bool = True
    reason: str = "approved active filesystem artifact field"


@dataclass(frozen=True)
class InventoryEntry:
    table: str
    primary_key: str
    column: str
    record_id: str
    artifact_class: ArtifactClass
    status: ResolutionStatus
    relative_suffix: str
    suffix_sha256: str
    stored_value_sha256: str
    proposed_value_sha256: str
    size_bytes: int | None
    reason: str
    old_value: str = field(repr=False)
    new_value: str = field(repr=False)


@dataclass
class MigrationReport:
    run_id: str
    generated_at: str
    mode: str
    database_sha256: str
    old_root_sha256: str
    new_root_sha256: str
    counts: dict[str, FieldCounts]
    entries: list[InventoryEntry]
    collision_warnings: list[dict[str, Any]]

    @property
    def remappable_count(self) -> int:
        return sum(item.remappable_count for item in self.counts.values())

    @property
    def unresolved_count(self) -> int:
        return sum(item.unresolved_count for item in self.counts.values())

    @property
    def containment_failure_count(self) -> int:
        return sum(item.containment_failure_count for item in self.counts.values())


@dataclass(frozen=True)
class ReportPaths:
    summary_json: Path
    summary_markdown: Path
    rollback_json: Path


@dataclass(frozen=True)
class ApplyResult:
    run_id: str
    rows_updated: int
    rows_updated_by_field: dict[str, int]
    pre_database_sha256: str
    post_database_sha256: str
    integrity_check: str
    foreign_key_violations: int
    rollback_mapping_path: Path | None


class MigrationApplyError(RuntimeError):
    pass


def _normalized(value: str | Path) -> str:
    return str(value).strip().replace("\\", "/").rstrip("/")


def _has_prefix(value: str, root: Path) -> bool:
    normalized_value = _normalized(value)
    normalized_root = _normalized(root)
    return normalized_value == normalized_root or normalized_value.startswith(normalized_root + "/")


def _validate_options(options: MigrationOptions) -> None:
    if not options.db_path.is_file():
        raise ValueError("database path does not exist or is not a file")
    if not options.old_root.is_absolute() or not options.new_root.is_absolute():
        raise ValueError("old and new roots must be absolute")
    old_root = options.old_root.resolve(strict=False)
    new_root = options.new_root.resolve(strict=False)
    if old_root == new_root:
        raise ValueError("old and new roots must be different")
    if not new_root.exists() or not new_root.is_dir():
        raise ValueError("new root does not exist or is not a directory")


def _direct_file_missing(value: str) -> bool:
    normalized = _normalized(value)
    if "://" in normalized:
        return True
    return not Path(normalized).is_file()


def _safe_entry(
    path_field: PathField,
    record_id: object,
    old_value: str,
    resolution: ArtifactResolution,
) -> InventoryEntry:
    resolved_path = resolution.path
    suffix = resolution.relative_suffix.as_posix() if resolution.relative_suffix is not None else ""
    new_value = str(resolved_path) if resolved_path is not None else ""
    size_bytes = resolved_path.stat().st_size if resolved_path is not None and resolved_path.is_file() else None
    return InventoryEntry(
        table=path_field.table,
        primary_key=path_field.primary_key,
        column=path_field.column,
        record_id=str(record_id),
        artifact_class=path_field.artifact_class,
        status=resolution.status,
        relative_suffix=suffix,
        suffix_sha256=sha256_text(suffix),
        stored_value_sha256=sha256_text(old_value),
        proposed_value_sha256=sha256_text(new_value),
        size_bytes=size_bytes,
        reason=resolution.reason,
        old_value=old_value,
        new_value=new_value,
    )


def inventory_database(options: MigrationOptions) -> MigrationReport:
    _validate_options(options)
    counts: dict[str, FieldCounts] = {}
    entries: list[InventoryEntry] = []
    proposed_targets: dict[str, list[tuple[str, str]]] = {}

    uri = f"file:{options.db_path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for path_field in APPROVED_PATH_FIELDS:
            key = f"{path_field.table}.{path_field.column}"
            summary = FieldCounts(table=path_field.table, column=path_field.column)
            counts[key] = summary
            rows = conn.execute(
                f'SELECT "{path_field.primary_key}" AS record_id, '
                f'"{path_field.column}" AS stored_value '
                f'FROM "{path_field.table}" WHERE {path_field.active_where}'
            ).fetchall()
            summary.record_count = len(rows)
            for row in rows:
                raw_value = row["stored_value"]
                value = "" if raw_value is None else str(raw_value)
                if not value.strip():
                    summary.null_blank_count += 1
                    continue

                is_old = _has_prefix(value, options.old_root)
                is_current = _has_prefix(value, options.new_root)
                if is_old:
                    summary.old_root_match_count += 1
                if is_current:
                    summary.already_current_count += 1
                if options.verify_files and _direct_file_missing(value):
                    summary.missing_file_count_before_remap += 1

                resolution = resolve_artifact_path(
                    value,
                    artifact_class=path_field.artifact_class,
                    data_root=options.new_root,
                    old_root=options.old_root,
                    require_exists=options.verify_files,
                )
                if resolution.path is not None and resolution.path.is_file():
                    summary.existing_file_count_after_remap += 1

                if is_old:
                    if resolution.status is ResolutionStatus.REMAPPED:
                        summary.remappable_count += 1
                    else:
                        summary.unresolved_count += 1
                        if resolution.status is ResolutionStatus.OUTSIDE_ALLOWED_ROOT:
                            summary.containment_failure_count += 1
                entry = _safe_entry(path_field, row["record_id"], value, resolution)
                entries.append(entry)
                if is_old and entry.new_value:
                    proposed_targets.setdefault(entry.new_value, []).append((key, entry.record_id))

    collision_warnings = [
        {
            "target_sha256": sha256_text(target),
            "references": [{"field": field_name, "record_id": record_id} for field_name, record_id in refs],
        }
        for target, refs in proposed_targets.items()
        if len(refs) > 1
    ]
    return MigrationReport(
        run_id=str(uuid.uuid4()),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        mode="apply" if options.apply else "dry-run",
        database_sha256=sha256_file(options.db_path),
        old_root_sha256=sha256_text(_normalized(options.old_root)),
        new_root_sha256=sha256_text(_normalized(options.new_root)),
        counts=counts,
        entries=entries,
        collision_warnings=collision_warnings,
    )


def _safe_report_payload(report: MigrationReport) -> dict[str, Any]:
    return {
        "migration_version": MIGRATION_VERSION,
        "run_id": report.run_id,
        "generated_at": report.generated_at,
        "mode": report.mode,
        "database_sha256": report.database_sha256,
        "old_root_sha256": report.old_root_sha256,
        "new_root_sha256": report.new_root_sha256,
        "remappable_count": report.remappable_count,
        "unresolved_count": report.unresolved_count,
        "containment_failure_count": report.containment_failure_count,
        "collision_warnings": report.collision_warnings,
        "counts": {key: asdict(value) for key, value in report.counts.items()},
        "entries": [
            {
                "table": entry.table,
                "column": entry.column,
                "record_id": entry.record_id,
                "artifact_class": entry.artifact_class.value,
                "status": entry.status.value,
                "relative_suffix": entry.relative_suffix,
                "suffix_sha256": entry.suffix_sha256,
                "stored_value_sha256": entry.stored_value_sha256,
                "proposed_value_sha256": entry.proposed_value_sha256,
                "size_bytes": entry.size_bytes,
                "reason": entry.reason,
            }
            for entry in report.entries
        ],
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Artifact Path Migration Summary",
        "",
        f"- Migration version: `{payload['migration_version']}`",
        f"- Run ID: `{payload['run_id']}`",
        f"- Mode: `{payload['mode']}`",
        f"- Remappable: {payload['remappable_count']}",
        f"- Unresolved: {payload['unresolved_count']}",
        f"- Containment failures: {payload['containment_failure_count']}",
        "",
        "| Field | Records | Old-root | Blank | Current | Missing before | Existing after | Remappable | Unresolved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, item in payload["counts"].items():
        lines.append(
            f"| `{key}` | {item['record_count']} | {item['old_root_match_count']} | "
            f"{item['null_blank_count']} | {item['already_current_count']} | "
            f"{item['missing_file_count_before_remap']} | {item['existing_file_count_after_remap']} | "
            f"{item['remappable_count']} | {item['unresolved_count']} |"
        )
    lines.extend(["", "Reports contain path metadata only; private content and absolute roots are excluded.", ""])
    return "\n".join(lines)


def write_reports(report: MigrationReport, report_dir: Path) -> ReportPaths:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = _safe_report_payload(report)
    summary_json = report_dir / SUMMARY_JSON
    summary_markdown = report_dir / SUMMARY_MARKDOWN
    rollback_json = report_dir / ROLLBACK_JSON
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_markdown.write_text(_markdown_report(payload), encoding="utf-8")
    rollback_payload = {
        "migration_version": MIGRATION_VERSION,
        "run_id": report.run_id,
        "database_sha256": report.database_sha256,
        "mappings": [
            {
                "table": entry.table,
                "column": entry.column,
                "record_id": entry.record_id,
                "relative_suffix": entry.relative_suffix,
                "old_value_sha256": entry.stored_value_sha256,
                "new_value_sha256": entry.proposed_value_sha256,
            }
            for entry in report.entries
            if entry.status is ResolutionStatus.REMAPPED
        ],
    }
    rollback_json.write_text(json.dumps(rollback_payload, indent=2) + "\n", encoding="utf-8")
    return ReportPaths(summary_json, summary_markdown, rollback_json)


def _write_protected_rollback_mapping(report: MigrationReport, output_path: Path) -> None:
    mappings = [
        {
            "table": entry.table,
            "primary_key": entry.primary_key,
            "column": entry.column,
            "record_id": entry.record_id,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
        }
        for entry in report.entries
        if entry.status is ResolutionStatus.REMAPPED
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "migration_version": MIGRATION_VERSION,
                "run_id": report.run_id,
                "database_sha256": report.database_sha256,
                "mappings": mappings,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    output_path.chmod(0o600)


def _record_migration_event(
    conn: sqlite3.Connection,
    *,
    report: MigrationReport,
    rows_updated_by_field: dict[str, int],
) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'operational_events'"
    ).fetchone()
    if not table_exists:
        raise MigrationApplyError("operational_events table is required for migration audit")
    details = {
        "migration_version": MIGRATION_VERSION,
        "run_id": report.run_id,
        "old_root_sha256": report.old_root_sha256,
        "new_root_sha256": report.new_root_sha256,
        "rows_updated_by_field": rows_updated_by_field,
        "unresolved_count": report.unresolved_count,
    }
    conn.execute(
        """
        INSERT INTO operational_events (
            event_type, severity, source, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "artifact_path_migration",
            "info",
            "p0a-migration",
            "Approved artifact path metadata migrated",
            json.dumps(details, sort_keys=True),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )


def apply_migration(
    options: MigrationOptions,
    report: MigrationReport,
    *,
    failure_hook: Callable[[sqlite3.Connection], None] | None = None,
) -> ApplyResult:
    _validate_options(options)
    if not options.apply:
        raise MigrationApplyError("apply mode was not explicitly selected")
    if not options.verify_files:
        raise MigrationApplyError("apply requires --verify-files")
    if not options.backup_confirmation.startswith("verified:"):
        raise MigrationApplyError("verified backup confirmation is required")
    if len(options.expected_db_sha256) != 64:
        raise MigrationApplyError("expected database SHA-256 is required")
    current_hash = sha256_file(options.db_path)
    if current_hash != options.expected_db_sha256 or report.database_sha256 != current_hash:
        raise MigrationApplyError("database hash differs from the reviewed dry-run baseline")
    if report.containment_failure_count:
        raise MigrationApplyError("containment failures block apply")
    if report.unresolved_count and not options.allow_missing:
        raise MigrationApplyError("unresolved active artifact paths block apply")

    mappings = [entry for entry in report.entries if entry.status is ResolutionStatus.REMAPPED]
    rollback_path = options.rollback_sql_output or options.report_dir / "protected-rollback-mapping.json"
    if mappings:
        _write_protected_rollback_mapping(report, rollback_path)

    conn = sqlite3.connect(str(options.db_path), timeout=30, isolation_level=None)
    rows_updated_by_field: dict[str, int] = {}
    committed = False
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        for entry in mappings:
            cursor = conn.execute(
                f'UPDATE "{entry.table}" SET "{entry.column}" = ? '
                f'WHERE "{entry.primary_key}" = ? AND "{entry.column}" = ?',
                (entry.new_value, entry.record_id, entry.old_value),
            )
            if cursor.rowcount != 1:
                raise MigrationApplyError(
                    f"reviewed value changed before update: {entry.table}.{entry.column} record {entry.record_id}"
                )
            key = f"{entry.table}.{entry.column}"
            rows_updated_by_field[key] = rows_updated_by_field.get(key, 0) + 1

        if mappings:
            _record_migration_event(conn, report=report, rows_updated_by_field=rows_updated_by_field)
        if failure_hook is not None:
            failure_hook(conn)
        integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity_check != "ok":
            raise MigrationApplyError(f"SQLite integrity check failed: {integrity_check}")
        foreign_key_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        if foreign_key_violations:
            raise MigrationApplyError(f"SQLite foreign-key check found {foreign_key_violations} violation(s)")
        conn.commit()
        committed = True
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise MigrationApplyError("committed migration WAL could not be checkpointed")
    except Exception as exc:
        conn.rollback()
        if mappings and not committed:
            rollback_path.unlink(missing_ok=True)
        if isinstance(exc, MigrationApplyError):
            raise
        raise MigrationApplyError(str(exc)) from exc
    finally:
        conn.close()

    return ApplyResult(
        run_id=report.run_id,
        rows_updated=len(mappings),
        rows_updated_by_field=rows_updated_by_field,
        pre_database_sha256=current_hash,
        post_database_sha256=sha256_file(options.db_path),
        integrity_check=integrity_check,
        foreign_key_violations=foreign_key_violations,
        rollback_mapping_path=rollback_path if mappings else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inventory and migrate approved artifact path metadata")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--new-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Inventory only (default)")
    mode.add_argument("--apply", action="store_true", help="Apply reviewed changes transactionally")
    parser.add_argument("--backup-confirmation", default="")
    parser.add_argument("--expected-db-sha256", default="")
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--rollback-sql-output", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = MigrationOptions(
        db_path=args.db_path,
        old_root=args.old_root,
        new_root=args.new_root,
        report_dir=args.report_dir,
        verify_files=args.verify_files,
        allow_missing=args.allow_missing,
        apply=args.apply,
        backup_confirmation=args.backup_confirmation,
        expected_db_sha256=args.expected_db_sha256,
        rollback_sql_output=args.rollback_sql_output,
    )
    report = inventory_database(options)
    paths = write_reports(report, options.report_dir)
    apply_result = apply_migration(options, report) if options.apply else None
    print(
        json.dumps(
            {
                "mode": report.mode,
                "run_id": report.run_id,
                "remappable_count": report.remappable_count,
                "unresolved_count": report.unresolved_count,
                "summary": paths.summary_json.name,
                "rows_updated": apply_result.rows_updated if apply_result is not None else 0,
                "post_database_sha256": (
                    apply_result.post_database_sha256 if apply_result is not None else report.database_sha256
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
