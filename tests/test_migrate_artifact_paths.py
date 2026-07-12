from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.storage.artifact_paths import APPROVED_PATH_FIELDS
from scripts.migrate_artifact_paths import (
    MigrationApplyError,
    MigrationOptions,
    apply_migration,
    inventory_database,
    main,
    write_reports,
)


OLD_ROOT = Path("/home/thenam176/novel_pipeline")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    data_root = tmp_path / "data"
    for name in ("raw", "cleaned", "translated", "covers", "audio"):
        (data_root / name).mkdir(parents=True, exist_ok=True)
    raw_target = data_root / "raw" / "book" / "chapter.txt"
    raw_target.parent.mkdir(parents=True)
    raw_target.write_text("private chapter fixture", encoding="utf-8")
    translated_target = data_root / "translated" / "book" / "chapter.txt"
    translated_target.parent.mkdir(parents=True)
    translated_target.write_text("translated fixture", encoding="utf-8")
    report_target = data_root / "audio" / "tts_jobs" / "job-1" / "report.json"
    report_target.parent.mkdir(parents=True)
    report_target.write_text("{}", encoding="utf-8")

    db_path = tmp_path / "pipeline.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE books (id INTEGER PRIMARY KEY, cover_path TEXT, notes TEXT);
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY,
                deleted_at TEXT,
                raw_text_path TEXT,
                cleaned_text_path TEXT,
                translated_text_path TEXT,
                content_html_path TEXT,
                audio_path TEXT,
                private_text TEXT
            );
            CREATE TABLE tts_jobs (
                id TEXT PRIMARY KEY,
                output_mp3_path TEXT,
                output_m4b_path TEXT,
                report_json_path TEXT
            );
            CREATE TABLE tts_chunks (id TEXT PRIMARY KEY, wav_path TEXT, mp3_path TEXT);
            CREATE TABLE operational_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                severity TEXT,
                source TEXT,
                message TEXT,
                details_json TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO books VALUES (1, '', ?)",
            ("historical /home/thenam176/novel_pipeline must not migrate",),
        )
        conn.execute(
            "INSERT INTO chapters VALUES (1, NULL, ?, NULL, ?, '', ?, ?)",
            (
                str(OLD_ROOT / "data/raw/book/chapter.txt"),
                str(translated_target),
                str(OLD_ROOT / "data/audio/missing.mp3"),
                "private chapter fixture",
            ),
        )
        conn.execute(
            "INSERT INTO chapters VALUES (2, '2026-01-01', ?, NULL, NULL, NULL, NULL, ?)",
            (str(OLD_ROOT / "data/raw/deleted.txt"), "archived private text"),
        )
        conn.execute(
            "INSERT INTO tts_jobs VALUES ('job-1', '', '', ?)",
            (str(OLD_ROOT / "data/audio/tts_jobs/job-1/report.json"),),
        )
        conn.execute("INSERT INTO tts_chunks VALUES ('chunk-1', NULL, '')")
        conn.commit()
    return db_path, data_root, "private chapter fixture"


def test_default_dry_run_does_not_mutate_database_and_writes_private_safe_reports(tmp_path: Path) -> None:
    db_path, data_root, private_text = create_fixture(tmp_path)
    report_dir = tmp_path / "reports"
    before = sha256_file(db_path)

    exit_code = main(
        [
            "--db-path",
            str(db_path),
            "--old-root",
            str(OLD_ROOT),
            "--new-root",
            str(data_root),
            "--report-dir",
            str(report_dir),
            "--verify-files",
        ]
    )

    assert exit_code == 0
    assert sha256_file(db_path) == before
    json_path = report_dir / "artifact-path-migration-summary.json"
    markdown_path = report_dir / "artifact-path-migration-summary.md"
    rollback_path = report_dir / "artifact-path-migration-rollback.json"
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert rollback_path.is_file()
    combined = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert str(OLD_ROOT) not in combined
    assert str(data_root) not in combined
    assert private_text not in combined

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["counts"]["chapters.raw_text_path"]["old_root_match_count"] == 1
    assert payload["counts"]["chapters.raw_text_path"]["existing_file_count_after_remap"] == 1
    assert payload["counts"]["chapters.audio_path"]["missing_file_count_before_remap"] == 1
    assert payload["counts"]["chapters.audio_path"]["existing_file_count_after_remap"] == 0
    assert payload["counts"]["chapters.translated_text_path"]["already_current_count"] == 1
    assert payload["remappable_count"] == 2
    assert payload["unresolved_count"] == 1


def test_inventory_reports_every_approved_field_and_excludes_inactive_rows(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    options = MigrationOptions(
        db_path=db_path,
        old_root=OLD_ROOT,
        new_root=data_root,
        report_dir=tmp_path / "reports",
        verify_files=True,
    )

    report = inventory_database(options)

    assert set(report.counts) == {f"{field.table}.{field.column}" for field in APPROVED_PATH_FIELDS}
    assert report.counts["chapters.raw_text_path"].record_count == 1
    assert report.counts["chapters.raw_text_path"].old_root_match_count == 1
    assert all(entry.record_id != "2" for entry in report.entries)
    assert {(entry.table, entry.column) for entry in report.entries} <= {
        (field.table, field.column) for field in APPROVED_PATH_FIELDS
    }


def test_reports_use_relative_suffixes_and_hashed_rollback_metadata(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    options = MigrationOptions(
        db_path=db_path,
        old_root=OLD_ROOT,
        new_root=data_root,
        report_dir=tmp_path / "reports",
        verify_files=True,
    )
    report = inventory_database(options)

    paths = write_reports(report, options.report_dir)
    rollback = json.loads(paths.rollback_json.read_text(encoding="utf-8"))

    assert rollback["mappings"]
    assert all("old_value" not in item and "new_value" not in item for item in rollback["mappings"])
    assert all(len(item["old_value_sha256"]) == 64 for item in rollback["mappings"])
    assert all(not item["relative_suffix"].startswith("/") for item in rollback["mappings"])


@pytest.mark.parametrize(
    ("old_root", "new_root", "message"),
    [
        (Path("/same"), Path("/same"), "different"),
        (Path("."), Path("."), "absolute"),
    ],
)
def test_inventory_rejects_unsafe_roots(
    tmp_path: Path,
    old_root: Path,
    new_root: Path,
    message: str,
) -> None:
    db_path, _, _ = create_fixture(tmp_path)
    options = MigrationOptions(
        db_path=db_path,
        old_root=old_root,
        new_root=new_root,
        report_dir=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match=message):
        inventory_database(options)


def test_inventory_rejects_nonexistent_new_root(tmp_path: Path) -> None:
    db_path, _, _ = create_fixture(tmp_path)
    options = MigrationOptions(
        db_path=db_path,
        old_root=OLD_ROOT,
        new_root=tmp_path / "missing-data-root",
        report_dir=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match="does not exist"):
        inventory_database(options)


def apply_options(
    db_path: Path,
    data_root: Path,
    report_dir: Path,
    *,
    allow_missing: bool = True,
) -> MigrationOptions:
    return MigrationOptions(
        db_path=db_path,
        old_root=OLD_ROOT,
        new_root=data_root,
        report_dir=report_dir,
        verify_files=True,
        allow_missing=allow_missing,
        apply=True,
        backup_confirmation="verified:test-backup",
        expected_db_sha256=sha256_file(db_path),
        rollback_sql_output=report_dir / "protected-rollback-mapping.json",
    )


def database_dump(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return "\n".join(conn.iterdump())


def test_apply_requires_explicit_backup_confirmation_and_reviewed_hash(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    base = apply_options(db_path, data_root, tmp_path / "reports")
    report = inventory_database(base)

    with pytest.raises(MigrationApplyError, match="backup confirmation"):
        apply_migration(
            MigrationOptions(**{**base.__dict__, "backup_confirmation": ""}),
            report,
        )
    with pytest.raises(MigrationApplyError, match="expected database SHA-256"):
        apply_migration(
            MigrationOptions(**{**base.__dict__, "expected_db_sha256": ""}),
            report,
        )


def test_apply_blocks_unresolved_active_artifacts_without_acceptance(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    options = apply_options(db_path, data_root, tmp_path / "reports", allow_missing=False)
    report = inventory_database(options)

    with pytest.raises(MigrationApplyError, match="unresolved"):
        apply_migration(options, report)


def test_apply_updates_only_approved_values_and_second_apply_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    report_dir = tmp_path / "reports"
    options = apply_options(db_path, data_root, report_dir)
    first_report = inventory_database(options)
    chmod_calls: list[tuple[Path, int]] = []
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        chmod_calls.append((path, mode))
        original_chmod(path, mode, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "chmod", record_chmod)

    first = apply_migration(options, first_report)

    assert first.rows_updated == 2
    assert first.integrity_check == "ok"
    assert first.foreign_key_violations == 0
    with sqlite3.connect(db_path) as conn:
        raw_path, translated_path, audio_path, private_text = conn.execute(
            "SELECT raw_text_path, translated_text_path, audio_path, private_text FROM chapters WHERE id = 1"
        ).fetchone()
        deleted_path = conn.execute("SELECT raw_text_path FROM chapters WHERE id = 2").fetchone()[0]
        notes = conn.execute("SELECT notes FROM books WHERE id = 1").fetchone()[0]
        event = conn.execute(
            "SELECT event_type, details_json FROM operational_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert raw_path == str((data_root / "raw/book/chapter.txt").resolve())
    assert translated_path == str((data_root / "translated/book/chapter.txt").resolve())
    assert audio_path == str(OLD_ROOT / "data/audio/missing.mp3")
    assert private_text == "private chapter fixture"
    assert deleted_path == str(OLD_ROOT / "data/raw/deleted.txt")
    assert str(OLD_ROOT) in notes
    assert event[0] == "artifact_path_migration"
    assert str(OLD_ROOT) not in event[1]
    assert (Path(options.rollback_sql_output), 0o600) in chmod_calls

    second_options = MigrationOptions(
        **{**options.__dict__, "expected_db_sha256": sha256_file(db_path)}
    )
    second_report = inventory_database(second_options)
    second = apply_migration(second_options, second_report)

    assert second.rows_updated == 0
    assert second.integrity_check == "ok"


def test_apply_post_hash_includes_committed_wal_changes(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    keeper = sqlite3.connect(db_path)
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    try:
        assert keeper.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        options = apply_options(db_path, data_root, tmp_path / "reports")
        report = inventory_database(options)

        result = apply_migration(options, report)
        wal_size_after_apply = wal_path.stat().st_size if wal_path.exists() else 0
    finally:
        keeper.close()

    with sqlite3.connect(db_path) as conn:
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    assert checkpoint[0] == 0
    assert wal_size_after_apply == 0
    assert result.post_database_sha256 == sha256_file(db_path)
    assert result.post_database_sha256 != result.pre_database_sha256


def test_apply_rolls_back_every_update_when_validation_fails(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    options = apply_options(db_path, data_root, tmp_path / "reports")
    report = inventory_database(options)
    before = database_dump(db_path)

    def fail_after_updates(_: sqlite3.Connection) -> None:
        raise RuntimeError("injected validation failure")

    with pytest.raises(MigrationApplyError, match="injected validation failure"):
        apply_migration(options, report, failure_hook=fail_after_updates)

    assert database_dump(db_path) == before


def test_apply_aborts_when_database_hash_changes_after_review(tmp_path: Path) -> None:
    db_path, data_root, _ = create_fixture(tmp_path)
    options = apply_options(db_path, data_root, tmp_path / "reports")
    report = inventory_database(options)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE books SET notes = 'changed after review' WHERE id = 1")
        conn.commit()

    with pytest.raises(MigrationApplyError, match="hash differs"):
        apply_migration(options, report)
