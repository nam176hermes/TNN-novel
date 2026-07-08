from __future__ import annotations

import io
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from scripts import ops


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
