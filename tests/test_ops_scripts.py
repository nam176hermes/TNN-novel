from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from scripts import ops


def _write_backup_sidecar(archive: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "backup_format_version": 2,
        "created_at": "2026-07-12T10:00:00",
        "encrypted": False,
        "secrets_included": False,
        "included_modules": ["database"],
        "excluded_modules": ["secrets"],
        "file_count": 1,
        "total_size_bytes": 8,
        "checksums": [{"path": "data/private.txt", "sha256": "a" * 64}],
    }
    payload.update(overrides)
    sidecar = archive.with_suffix(archive.suffix + ops.BACKUP_MANIFEST_SUFFIX)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return sidecar


def test_list_backups_never_opens_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    ready.write_bytes(b"artifact")
    _write_backup_sidecar(ready)
    missing = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz"
    missing.write_bytes(b"large-content-is-irrelevant")
    monkeypatch.setattr(ops.tarfile, "open", lambda *args, **kwargs: pytest.fail("listing opened archive"))

    items = {item["filename"]: item for item in ops.list_backups(tmp_path)}

    assert items[ready.name]["metadata_status"] == "READY"
    assert items[missing.name]["metadata_status"] == "METADATA_MISSING"
    assert "checksums" not in items[ready.name]["manifest"]
    assert "private.txt" not in json.dumps(items)


def test_list_backups_classifies_entries_independently(tmp_path: Path) -> None:
    malformed = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    malformed.write_bytes(b"artifact")
    malformed.with_suffix(malformed.suffix + ops.BACKUP_MANIFEST_SUFFIX).write_text("{", encoding="utf-8")

    zero = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz"
    zero.touch()

    orphan_archive = tmp_path / "novel-pipeline-backup-20260712-080000.tar.gz"
    _write_backup_sidecar(orphan_archive)

    unsupported = tmp_path / "novel-pipeline-backup-20260712-070000.zip"
    unsupported.write_bytes(b"zip")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    items = {item["filename"]: item for item in ops.list_backups(tmp_path)}

    assert items[malformed.name]["metadata_status"] == "METADATA_INVALID"
    assert items[zero.name]["metadata_status"] == "ARTIFACT_INVALID"
    assert items[orphan_archive.name]["metadata_status"] == "ARTIFACT_MISSING"
    assert items[unsupported.name]["metadata_status"] == "UNSUPPORTED_FORMAT"
    assert "notes.txt" not in items
    assert all(not item.get("download_url") for item in items.values())


def test_list_backups_rejects_oversized_and_symlink_sidecars(tmp_path: Path) -> None:
    oversized = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    oversized.write_bytes(b"artifact")
    oversized_sidecar = oversized.with_suffix(oversized.suffix + ops.BACKUP_MANIFEST_SUFFIX)
    oversized_sidecar.write_bytes(b"x" * (ops.MAX_BACKUP_SIDECAR_BYTES + 1))

    linked = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz"
    linked.write_bytes(b"artifact")
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    linked.with_suffix(linked.suffix + ops.BACKUP_MANIFEST_SUFFIX).symlink_to(external)

    items = {item["filename"]: item for item in ops.list_backups(tmp_path)}

    assert items[oversized.name]["metadata_status"] == "METADATA_INVALID"
    assert items[linked.name]["metadata_status"] == "METADATA_INVALID"


def test_list_backups_rejects_absolute_or_mismatched_sidecar_metadata(tmp_path: Path) -> None:
    absolute = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    absolute.write_bytes(b"artifact")
    _write_backup_sidecar(absolute, app_version="/home/private/build")
    mismatched = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz"
    mismatched.write_bytes(b"artifact")
    _write_backup_sidecar(mismatched, backup_filename="different.tar.gz")

    items = {item["filename"]: item for item in ops.list_backups(tmp_path)}

    assert items[absolute.name]["metadata_status"] == "METADATA_INVALID"
    assert items[mismatched.name]["metadata_status"] == "METADATA_INVALID"
    assert "/home/private" not in json.dumps(items)


def test_create_backup_writes_compact_sidecar(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "chapter.txt").write_text("private", encoding="utf-8")

    archive = ops.create_backup(
        data_dir=data_dir,
        out_dir=tmp_path / "backups",
        record_event=False,
    )

    sidecar = ops.backup_sidecar_path(archive)
    sidecar_text = sidecar.read_text(encoding="utf-8")
    metadata = json.loads(sidecar_text)
    assert metadata["sidecar_schema_version"] == 1
    assert metadata["backup_filename"] == archive.name
    assert metadata["archive_size_bytes"] == archive.stat().st_size
    assert metadata["artifact_state"] == "READY"
    assert "checksums" not in metadata
    assert "chapter.txt" not in sidecar_text

    with tarfile.open(archive, "r:gz") as handle:
        internal = json.loads(handle.extractfile("manifest.json").read().decode("utf-8"))
    assert internal["checksums"][0]["path"] == "data/chapter.txt"


def test_atomic_sidecar_failure_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    archive.write_bytes(b"artifact")
    monkeypatch.setattr(
        ops.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        ops.write_backup_sidecar_atomic(archive, {"sidecar_schema_version": 1})

    assert not ops.backup_sidecar_path(archive).exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_metadata_repair_dry_run_apply_and_idempotency(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "chapter.txt").write_text("source", encoding="utf-8")
    source = ops.create_backup(
        data_dir=data_dir,
        out_dir=tmp_path / "source",
        record_event=False,
    )
    rehearsal = tmp_path / "rehearsal"
    rehearsal.mkdir()
    archive = rehearsal / source.name
    shutil.copy2(source, archive)
    ops.backup_sidecar_path(archive).unlink(missing_ok=True)
    before = ops.sha256_file(archive)

    dry = ops.repair_backup_metadata(
        rehearsal,
        filename=archive.name,
        all_missing=False,
        apply=False,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )
    assert dry["would_write"] == 1
    assert dry["written"] == 0
    assert not ops.backup_sidecar_path(archive).exists()

    first = ops.repair_backup_metadata(
        rehearsal,
        filename=archive.name,
        all_missing=False,
        apply=True,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )
    second = ops.repair_backup_metadata(
        rehearsal,
        filename=archive.name,
        all_missing=False,
        apply=True,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )

    assert first["written"] == 1
    assert second["written"] == 0
    assert second["skipped_valid"] == 1
    assert ops.sha256_file(archive) == before
    assert ops.list_backups(rehearsal)[0]["metadata_status"] == "READY"


def test_metadata_repair_derives_safe_metadata_for_manifestless_legacy_archive(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "data" / "raw").mkdir(parents=True)
    (source / "data" / "pipeline.db").write_bytes(b"sqlite-fixture")
    (source / "data" / "raw" / "chapter.txt").write_text("private", encoding="utf-8")
    (source / ".env.example").write_text("SAFE=example\n", encoding="utf-8")
    archive = tmp_path / "novel-pipeline-backup-20260630-101633.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source / "data", arcname="data")
        handle.add(source / ".env.example", arcname=".env.example")
    before = ops.sha256_file(archive)

    result = ops.repair_backup_metadata(
        tmp_path,
        filename=archive.name,
        all_missing=False,
        apply=True,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )

    metadata = ops.read_backup_sidecar(archive)
    assert result["written"] == 1
    assert metadata["backup_format_version"] == 1
    assert metadata["secrets_included"] is False
    assert metadata["included_modules"] == ["database", "uploads"]
    assert metadata["file_count"] == 2
    assert metadata["total_size_bytes"] == len(b"sqlite-fixture") + len(b"private")
    assert ops.sha256_file(archive) == before


def test_metadata_repair_rejects_unsafe_manifestless_archive(tmp_path: Path) -> None:
    archive = tmp_path / "novel-pipeline-backup-20260630-101633.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        member = tarfile.TarInfo("../escape.txt")
        member.size = 1
        handle.addfile(member, io.BytesIO(b"x"))

    result = ops.repair_backup_metadata(
        tmp_path,
        filename=archive.name,
        all_missing=False,
        apply=True,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )

    assert result["failed"] == 1
    assert not ops.backup_sidecar_path(archive).exists()


def test_metadata_repair_reports_corrupt_and_encrypted_archives_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corrupt = tmp_path / "novel-pipeline-backup-20260712-100000.tar.gz"
    corrupt.write_bytes(b"not-a-tar")
    encrypted = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz.enc"
    encrypted.write_bytes(b"encrypted")
    monkeypatch.delenv("BACKUP_PASSPHRASE", raising=False)

    result = ops.repair_backup_metadata(
        tmp_path,
        filename=None,
        all_missing=True,
        apply=False,
        overwrite=False,
        passphrase_env="BACKUP_PASSPHRASE",
        report_dir=None,
    )

    assert result["failed"] == 2
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert "passphrase" not in serialized.lower()
    assert not ops.backup_sidecar_path(corrupt).exists()
    assert not ops.backup_sidecar_path(encrypted).exists()


def test_explicit_archive_inspection_rejects_unsafe_passphrase_env_name(tmp_path: Path) -> None:
    encrypted = tmp_path / "novel-pipeline-backup-20260712-090000.tar.gz.enc"
    encrypted.write_bytes(b"encrypted")

    with pytest.raises(ValueError, match="environment variable name"):
        ops.inspect_backup_archive_explicitly(
            encrypted,
            passphrase_env="BACKUP-PASSPHRASE",
        )


def test_backup_metadata_repair_cli_defaults_to_dry_run() -> None:
    args = ops.build_parser().parse_args(
        ["backup-metadata-repair", "--backup-dir", "backups", "--all-missing"]
    )

    assert args.command == "backup-metadata-repair"
    assert args.apply is False
    assert args.all_missing is True


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    (data_dir / "translated").mkdir()
    (data_dir / "raw" / "chapter.txt").write_text("source", encoding="utf-8")
    (data_dir / "translated" / "chapter.txt").write_text("ban dich", encoding="utf-8")
    out_dir = tmp_path / "backups"

    backup_path = ops.create_backup(data_dir=data_dir, out_dir=out_dir, label="test")
    restored_dir = ops.restore_backup(backup_path, tmp_path / "restored")

    assert backup_path.exists()
    assert restored_dir == tmp_path / "restored"
    assert (restored_dir / "raw" / "chapter.txt").read_text(encoding="utf-8") == "source"
    assert (restored_dir / "translated" / "chapter.txt").read_text(encoding="utf-8") == "ban dich"

    manifest_sidecar = backup_path.with_suffix(backup_path.suffix + ops.BACKUP_MANIFEST_SUFFIX)
    assert manifest_sidecar.exists()
    manifest = ops.read_backup_manifest(backup_path)
    assert manifest["backup_format_version"] == 2
    assert "database" in manifest["included_modules"]
    assert manifest["secrets_included"] is False


def test_create_backup_can_exclude_exports_and_job_logs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "exports").mkdir(parents=True)
    (data_dir / "logs").mkdir()
    (data_dir / "audio").mkdir()
    (data_dir / "exports" / "book.txt").write_text("export", encoding="utf-8")
    (data_dir / "logs" / "runtime.log").write_text("log", encoding="utf-8")
    (data_dir / "audio" / "chapter.mp3").write_bytes(b"audio")

    backup_path = ops.create_backup(
        data_dir=data_dir,
        out_dir=tmp_path / "backups",
        include_audio=True,
        include_exports=False,
        include_job_logs=False,
    )

    manifest = ops.read_backup_manifest(backup_path)
    assert "audio" in manifest["included_modules"]
    assert "exports" in manifest["excluded_modules"]
    assert "job_logs" in manifest["excluded_modules"]

    with tarfile.open(backup_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "data/audio/chapter.mp3" in names
    assert "data/exports/book.txt" not in names
    assert "data/logs/runtime.log" not in names


def test_create_backup_can_skip_operational_event_for_pre_rehearsal_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database import db as database_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "pipeline.db") as conn:
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
    calls: list[Path] = []

    def record_event(db_path: Path, **_: object) -> None:
        calls.append(db_path)

    monkeypatch.setattr(database_db, "record_operational_event", record_event)

    ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups-default", record_event=True)
    assert calls == [data_dir / "pipeline.db"]

    calls.clear()
    ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups-gated", record_event=False)
    assert calls == []


def test_backup_cli_and_shell_expose_no_event_gate() -> None:
    parser = ops.build_parser()
    args = parser.parse_args(["backup", "--no-record-event"])

    assert args.no_record_event is True
    shell = Path("scripts/backup-local.sh").read_text(encoding="utf-8")
    assert 'record_event = os.getenv("BACKUP_RECORD_EVENT", "1") != "0"' in shell
    assert "record_event=record_event" in shell


def test_create_backup_can_skip_checkpoint_without_changing_source_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('unchanged')")
        conn.commit()
    before = ops.sha256_file(db_path)
    checkpoint_calls: list[Path] = []
    monkeypatch.setattr(ops, "sqlite_checkpoint", lambda path: checkpoint_calls.append(path))

    backup_path = ops.create_backup(
        data_dir=data_dir,
        out_dir=tmp_path / "backups",
        record_event=False,
        checkpoint_database=False,
    )

    assert backup_path.is_file()
    assert checkpoint_calls == []
    assert ops.sha256_file(db_path) == before


def test_backup_cli_and_shell_expose_no_checkpoint_gate() -> None:
    parser = ops.build_parser()
    args = parser.parse_args(["backup", "--no-checkpoint"])

    assert args.no_checkpoint is True
    shell = Path("scripts/backup-local.sh").read_text(encoding="utf-8")
    assert 'checkpoint_database = os.getenv("BACKUP_CHECKPOINT", "1") != "0"' in shell
    assert "checkpoint_database=checkpoint_database" in shell


def test_restore_rejects_unsafe_archive_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    payload = b"owned"

    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(payload)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="Unsafe archive member"):
        ops.restore_backup(archive_path, tmp_path / "restore")


def test_restore_refuses_non_empty_target_without_force(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "file.txt").write_text("data", encoding="utf-8")
    backup_path = ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups")
    target_dir = tmp_path / "existing"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ops.restore_backup(backup_path, target_dir)

    ops.restore_backup(backup_path, target_dir, force=True)
    assert (target_dir / "file.txt").read_text(encoding="utf-8") == "data"


def test_ops_parser_exposes_expected_commands() -> None:
    parser = ops.build_parser()
    help_text = parser.format_help()

    assert "doctor" in help_text
    assert "backup" in help_text
    assert "restore" in help_text
    assert "restore-drill" in help_text
    assert "repair-db" in help_text
    assert "rotate-logs" in help_text
    assert "set-provider-key" in help_text
    assert "smoke" in help_text
    assert "smoke-public" in help_text


def test_smoke_accepts_redacted_system_status_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url.endswith("/api/health"):
            return {"status": "ok"}
        if url.endswith("/api/ready"):
            return {"status": "ok"}
        if url.endswith("/api/auth/login"):
            return {"access_token": "access-token"}
        if url.endswith("/api/providers"):
            return {"providers": []}
        if url.endswith("/api/system/status"):
            return {
                "api_ready": True,
                "database_available": True,
                "data_directory_available": True,
                "storage_health": "healthy",
                "storage_label": "Configured data storage",
            }
        raise AssertionError(f"unexpected json request: {method} {url} {kwargs}")

    monkeypatch.setattr(ops, "_request_json", fake_request_json)

    result = ops.run_smoke(
        base_url="http://127.0.0.1:7860",
        username="operator",
        password="strong-password",
    )

    assert result == 0
    assert "OK smoke" in capsys.readouterr().out


def test_smoke_rejects_absolute_path_fields_in_system_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url.endswith("/api/health") or url.endswith("/api/ready"):
            return {"status": "ok"}
        if url.endswith("/api/auth/login"):
            return {"access_token": "access-token"}
        if url.endswith("/api/providers"):
            return {"providers": []}
        if url.endswith("/api/system/status"):
            return {
                "api_ready": True,
                "database_available": True,
                "data_directory_available": True,
                "database_path": "/private/operator/pipeline.db",
            }
        raise AssertionError(f"unexpected json request: {method} {url} {kwargs}")

    monkeypatch.setattr(ops, "_request_json", fake_request_json)

    with pytest.raises(RuntimeError, match="absolute path fields"):
        ops.run_smoke(
            base_url="http://127.0.0.1:7860",
            username="operator",
            password="strong-password",
        )


def test_batch_local_script_help_status_and_logs(tmp_path: Path) -> None:
    script = Path("scripts/batch-local.sh")
    subprocess.run(["bash", "-n", str(script)], check=True)

    env = {**os.environ, "DATA_DIR": str(tmp_path / "data")}
    help_result = subprocess.run(
        ["bash", str(script), "--help"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    assert "translate --book-id" in help_result.stdout
    assert "tts --book-id" in help_result.stdout

    status_result = subprocess.run(
        ["bash", str(script), "status"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    assert "No local batch pid files" in status_result.stdout
    assert str(tmp_path / "data" / "logs" / "runtime") in status_result.stdout

    logs_result = subprocess.run(
        ["bash", str(script), "logs"],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    assert "No local batch logs" in logs_result.stdout
    assert str(tmp_path / "data" / "logs" / "runtime") in logs_result.stdout


def test_smoke_public_validates_public_deployment_basics(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    responses: dict[str, tuple[int, dict[str, str]]] = {
        "https://novel.example.com/docs": 404,
        "https://novel.example.com/openapi.json": 404,
        "https://novel.example.com/redoc": 404,
        "https://novel.example.com/covers/__public_smoke_probe__.jpg": 401,
        "https://novel.example.com/book-assets/__public_smoke_probe__.jpg": 401,
        "https://novel.example.com/data/pipeline.db": 404,
    }
    responses = {
        url: (
            status,
            {"cache-control": "private, no-store", "pragma": "no-cache"}
            if "/covers/" in url or "/book-assets/" in url
            else {},
        )
        for url, status in responses.items()
    }

    def fake_request_json(method: str, url: str, **kwargs):
        if url == "https://novel.example.com/api/ready":
            return {
                "status": "ok",
                "checks": {
                    "database": True,
                    "storage": True,
                    "jobs": True,
                    "public_deploy": True,
                },
                "details": {"database": "reachable", "storage": "reachable", "public_deploy": "enabled"},
            }
        if url == "https://novel.example.com/api/auth/login":
            assert kwargs["payload"] == {"username": "operator", "password": "strong-password"}
            return {"access_token": "access-token"}
        if url == "https://novel.example.com/api/system/status":
            assert kwargs["headers"]["Authorization"] == "Bearer access-token"
            return {"api_ready": True}
        raise AssertionError(f"unexpected json request: {method} {url}")

    def fake_request_status_headers(method: str, url: str, **kwargs):
        if method == "OPTIONS" and url == "https://novel.example.com/api/auth/login":
            return 200, {"access-control-allow-origin": "https://novel.example.com"}
        return responses[url]

    monkeypatch.setattr(ops, "_request_json", fake_request_json)
    monkeypatch.setattr(ops, "_request_status", lambda method, url, **kwargs: responses[url][0])
    monkeypatch.setattr(ops, "_request_status_headers", fake_request_status_headers, raising=False)

    result = ops.run_smoke_public(
        base_url="https://novel.example.com",
        username="operator",
        password="strong-password",
        data_probe_path="data/pipeline.db",
    )

    assert result == 0
    assert "OK public smoke" in capsys.readouterr().out


def test_smoke_public_fails_when_docs_are_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url == "https://novel.example.com/api/ready":
            return {"status": "ok", "checks": {"public_deploy": True}, "details": {"public_deploy": "enabled"}}
        if url == "https://novel.example.com/api/auth/login":
            return {"access_token": "access-token"}
        if url == "https://novel.example.com/api/system/status":
            return {"api_ready": True}
        raise AssertionError(f"unexpected json request: {method} {url}")

    def fake_request_status_headers(method: str, url: str, **kwargs):
        return (200, {}) if url.endswith("/docs") else (404, {})

    monkeypatch.setattr(ops, "_request_json", fake_request_json)
    monkeypatch.setattr(ops, "_request_status", lambda method, url, **kwargs: 200 if url.endswith("/docs") else 404)
    monkeypatch.setattr(ops, "_request_status_headers", fake_request_status_headers, raising=False)

    with pytest.raises(RuntimeError, match="/docs must be disabled"):
        ops.run_smoke_public(
            base_url="https://novel.example.com",
            username="operator",
            password="strong-password",
        )


def test_smoke_public_fails_when_ready_leaks_internal_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url == "https://novel.example.com/api/ready":
            return {
                "status": "ok",
                "checks": {"database": True},
                "details": {"database": "/home/operator/novel_pipeline/data/pipeline.db"},
            }
        if url == "https://novel.example.com/api/auth/login":
            return {"access_token": "access-token"}
        if url == "https://novel.example.com/api/system/status":
            return {"api_ready": True}
        raise AssertionError(f"unexpected json request: {method} {url}")

    monkeypatch.setattr(ops, "_request_json", fake_request_json)
    monkeypatch.setattr(ops, "_request_status", lambda method, url, **kwargs: 404)

    with pytest.raises(RuntimeError, match="/api/ready leaks sensitive public diagnostics"):
        ops.run_smoke_public(
            base_url="https://novel.example.com",
            username="operator",
            password="strong-password",
        )


def test_smoke_public_fails_when_asset_probe_is_publicly_cacheable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url == "https://novel.example.com/api/ready":
            return {"status": "ok", "checks": {"public_deploy": True}, "details": {"public_deploy": "enabled"}}
        if url == "https://novel.example.com/api/auth/login":
            return {"access_token": "access-token"}
        if url == "https://novel.example.com/api/system/status":
            return {"api_ready": True}
        raise AssertionError(f"unexpected json request: {method} {url}")

    def fake_request_status_headers(method: str, url: str, **kwargs):
        if method == "OPTIONS":
            return 200, {"access-control-allow-origin": "https://novel.example.com"}
        if url.endswith("/docs") or url.endswith("/openapi.json") or url.endswith("/redoc"):
            return 404, {}
        if "/covers/" in url or "/book-assets/" in url:
            return 401, {"cache-control": "public, max-age=3600"}
        return 404, {}

    monkeypatch.setattr(ops, "_request_json", fake_request_json)
    monkeypatch.setattr(ops, "_request_status", lambda method, url, **kwargs: 404 if "assets" not in url else 401)
    monkeypatch.setattr(ops, "_request_status_headers", fake_request_status_headers, raising=False)

    with pytest.raises(RuntimeError, match="must not be publicly cacheable"):
        ops.run_smoke_public(
            base_url="https://novel.example.com",
            username="operator",
            password="strong-password",
        )


def test_smoke_public_fails_when_cors_origin_is_not_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(method: str, url: str, **kwargs):
        if url == "https://novel.example.com/api/ready":
            return {"status": "ok", "checks": {"public_deploy": True}, "details": {"public_deploy": "enabled"}}
        raise AssertionError(f"unexpected json request: {method} {url}")

    def fake_request_status_headers(method: str, url: str, **kwargs):
        if method == "OPTIONS":
            return 200, {"access-control-allow-origin": "*"}
        if url.endswith("/docs") or url.endswith("/openapi.json") or url.endswith("/redoc"):
            return 404, {}
        if "/covers/" in url or "/book-assets/" in url:
            return 401, {"cache-control": "private, no-store"}
        return 404, {}

    monkeypatch.setattr(ops, "_request_json", fake_request_json)
    monkeypatch.setattr(ops, "_request_status", lambda method, url, **kwargs: 404)
    monkeypatch.setattr(ops, "_request_status_headers", fake_request_status_headers, raising=False)

    with pytest.raises(RuntimeError, match="CORS preflight must allow exactly"):
        ops.run_smoke_public(
            base_url="https://novel.example.com",
            username="operator",
            password="strong-password",
        )


def test_update_env_file_value_sets_supported_provider_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MOBILE_API_ADMIN_USERNAME=admin\nGEMINI_API_KEY=old\n", encoding="utf-8")

    ops.update_env_file_value(env_path, "GEMINI_API_KEY", " new-secret \n")
    ops.update_env_file_value(env_path, "OPENROUTER_API_KEY", "router-secret")

    content = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=new-secret" in content
    assert "GEMINI_API_KEY=old" not in content
    assert "OPENROUTER_API_KEY=router-secret" in content
    assert "MOBILE_API_ADMIN_USERNAME=admin" in content


def test_update_env_file_value_rejects_unsupported_or_empty_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    with pytest.raises(ValueError, match="Unsupported provider key"):
        ops.update_env_file_value(env_path, "MOBILE_API_SECRET", "secret")
    with pytest.raises(ValueError, match="value is empty"):
        ops.update_env_file_value(env_path, "GEMINI_API_KEY", "  ")


def test_repair_database_removes_orphan_chapters_and_empty_stale_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY,
                book_id INTEGER NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT,
                FOREIGN KEY (book_id) REFERENCES books(id)
            );
            INSERT INTO books (id, title) VALUES (1, 'Book');
            INSERT INTO chapters (id, book_id, chapter_number, title) VALUES
                (1, 1, 1, 'Valid'),
                (2, 99, 1, 'Orphan');
            """
        )
    (data_dir / "novel_pipeline.db").touch()

    result = ops.repair_database(
        data_dir=data_dir,
        out_dir=tmp_path / "backups",
        remove_empty_stale_db=True,
    )

    assert Path(result["backup_path"]).exists()
    assert result["deleted_orphan_chapters"] == 1
    assert result["removed_empty_stale_db"] is True
    assert result["remaining_fk_violations"] == []
    assert not (data_dir / "novel_pipeline.db").exists()
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT id FROM chapters ORDER BY id").fetchall()
    assert rows == [(1,)]


def test_rotate_runtime_logs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    runtime_dir = data_dir / "logs" / "runtime"
    runtime_dir.mkdir(parents=True)
    log_path = runtime_dir / "mobile-api.log"
    log_path.write_text("old log", encoding="utf-8")

    rotated = ops.rotate_runtime_logs(data_dir=data_dir, force=True, keep=2)

    assert rotated == [str(log_path)]
    assert log_path.read_text(encoding="utf-8") == ""
    assert (runtime_dir / "mobile-api.log.1").read_text(encoding="utf-8") == "old log"


def test_rotate_backup_files_keeps_newest_plain_and_encrypted_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    names = [
        "novel-pipeline-backup-20260101-000001.tar.gz",
        "novel-pipeline-backup-20260101-000002.tar.gz",
        "novel-pipeline-backup-20260101-000003.tar.gz.enc",
        "novel-pipeline-backup-20260101-000004.tar.gz",
    ]
    for index, name in enumerate(names):
        path = backup_dir / name
        path.write_text(name, encoding="utf-8")
        os.utime(path, (1000 + index, 1000 + index))

    removed = ops.rotate_backup_files(backup_dir, keep=2)

    assert [Path(path).name for path in removed] == names[:2]
    assert sorted(path.name for path in backup_dir.iterdir()) == sorted(names[2:])


def test_restore_drill_verifies_plain_backup_without_touching_live_data(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "pipeline.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO books (title) VALUES ('Live Book')")
    (data_dir / "raw").mkdir()
    (data_dir / "raw" / "chapter.txt").write_text("source", encoding="utf-8")
    backup_path = ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups")

    result = ops.restore_drill(backup_path, work_dir=tmp_path / "restore-drill")

    assert result["ok"] is True
    assert result["sqlite_integrity"] == "ok"
    assert result["restored_dir"] != str(data_dir)
    assert (data_dir / "raw" / "chapter.txt").read_text(encoding="utf-8") == "source"


def test_restore_drill_verifies_encrypted_backup_when_passphrase_is_provided(tmp_path: Path) -> None:
    if not shutil.which("openssl"):
        pytest.skip("openssl is not installed")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(str(data_dir / "pipeline.db")) as conn:
        conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    backup_path = ops.create_backup(data_dir=data_dir, out_dir=tmp_path / "backups")
    encrypted_path = backup_path.with_suffix(backup_path.suffix + ".enc")
    passphrase = "restore drill passphrase"
    env = {**os.environ, "BACKUP_PASSPHRASE": passphrase}
    subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-iter",
            "200000",
            "-in",
            str(backup_path),
            "-out",
            str(encrypted_path),
            "-pass",
            "env:BACKUP_PASSPHRASE",
        ],
        check=True,
        env=env,
    )

    result = ops.restore_drill(
        encrypted_path,
        work_dir=tmp_path / "restore-drill-encrypted",
        passphrase=passphrase,
    )

    assert result["ok"] is True
    assert result["encrypted"] is True
    assert result["sqlite_integrity"] == "ok"
