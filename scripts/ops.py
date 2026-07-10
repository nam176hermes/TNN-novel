#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_BACKUP_DIR = ROOT / "backups"
RUNTIME_SUBDIRS = ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs")
DEFAULT_USER_AGENT = "novel-pipeline-smoke/1.0"
PROVIDER_KEY_NAMES = ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
BACKUP_GLOB_PATTERNS = ("novel-pipeline-backup-*.tar.gz", "novel-pipeline-backup-*.tar.gz.enc")
BACKUP_MANIFEST_SUFFIX = ".manifest.json"
BACKUP_MODULE_SUBDIRS = {
    "uploads": ("raw", "cleaned", "translated", "inbox"),
    "covers": ("covers",),
    "book_assets": ("book_assets",),
    "audio": ("audio",),
    "exports": ("exports",),
    "job_logs": ("logs",),
    "glossary_qa": ("glossary",),
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str
    severity: str = "error"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def update_env_file_value(env_path: Path, key: str, value: str) -> None:
    if key not in PROVIDER_KEY_NAMES:
        raise ValueError(f"Unsupported provider key: {key}")
    value = value.strip()
    if not value:
        raise ValueError(f"{key} value is empty")

    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated_lines: list[str] = []
    replaced = False
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            if not replaced:
                updated_lines.append(f"{key}={value}")
                replaced = True
            continue
        updated_lines.append(line)
    if not replaced:
        if updated_lines and updated_lines[-1] != "":
            updated_lines.append("")
        updated_lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass


def resolve_data_dir(value: str | None = None) -> Path:
    if value:
        data_dir = Path(value)
    else:
        try:
            from app.config import settings

            return settings.resolved_data_dir
        except Exception:
            data_dir = Path(os.getenv("DATA_DIR", "data"))

    if data_dir.is_absolute():
        return data_dir
    return ROOT / data_dir


def ensure_runtime_dirs(data_dir: Path) -> None:
    for subdir in RUNTIME_SUBDIRS:
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)


def sqlite_checkpoint(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def sqlite_integrity_ok(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return bool(row and row[0] == "ok")


def sqlite_foreign_key_violations(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    return [
        {
            "table": row[0],
            "rowid": row[1],
            "parent": row[2],
            "fkid": row[3],
        }
        for row in rows
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def delete_orphan_chapters(db_path: Path) -> int:
    if not db_path.exists() or db_path.stat().st_size == 0:
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            """
            DELETE FROM chapters
            WHERE NOT EXISTS (
                SELECT 1 FROM books WHERE books.id = chapters.book_id
            )
            """
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def remove_empty_stale_database(data_dir: Path) -> bool:
    stale_db = data_dir / "novel_pipeline.db"
    if stale_db.exists() and stale_db.stat().st_size == 0:
        stale_db.unlink()
        return True
    return False


def repair_database(
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    *,
    remove_empty_stale_db: bool = False,
) -> dict[str, Any]:
    resolved_data_dir = (data_dir or resolve_data_dir()).resolve()
    backup_path = create_backup(resolved_data_dir, out_dir, label="pre-repair")
    db_path = resolved_data_dir / "pipeline.db"
    deleted_orphan_chapters = delete_orphan_chapters(db_path)
    removed_stale_db = remove_empty_stale_database(resolved_data_dir) if remove_empty_stale_db else False
    remaining_fk_violations = sqlite_foreign_key_violations(db_path)
    return {
        "backup_path": str(backup_path),
        "deleted_orphan_chapters": deleted_orphan_chapters,
        "removed_empty_stale_db": removed_stale_db,
        "remaining_fk_violations": remaining_fk_violations,
    }


def rotate_runtime_logs(
    data_dir: Path | None = None,
    *,
    max_bytes: int = 1_000_000,
    keep: int = 5,
    force: bool = False,
) -> list[str]:
    if keep < 1:
        raise ValueError("keep must be >= 1")
    runtime_dir = (data_dir or resolve_data_dir()) / "logs" / "runtime"
    if not runtime_dir.exists():
        return []

    rotated: list[str] = []
    for log_path in sorted(runtime_dir.glob("*.log")):
        if not force and log_path.stat().st_size <= max_bytes:
            continue

        oldest = log_path.with_name(f"{log_path.name}.{keep}")
        oldest.unlink(missing_ok=True)
        for index in range(keep - 1, 0, -1):
            current = log_path.with_name(f"{log_path.name}.{index}")
            if current.exists():
                current.rename(log_path.with_name(f"{log_path.name}.{index + 1}"))
        log_path.rename(log_path.with_name(f"{log_path.name}.1"))
        log_path.touch()
        rotated.append(str(log_path))
    return rotated


def create_backup(
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    *,
    include_env: bool = False,
    include_audio: bool = True,
    include_exports: bool = False,
    include_job_logs: bool = False,
    label: str | None = None,
    keep: int | None = None,
) -> Path:
    source_dir = (data_dir or resolve_data_dir()).resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {source_dir}")

    destination_dir = (out_dir or DEFAULT_BACKUP_DIR).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    sqlite_checkpoint(source_dir / "pipeline.db")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    backup_path = destination_dir / f"novel-pipeline-backup-{stamp}{suffix}.tar.gz"

    excluded_roots: set[str] = set()
    if not include_audio:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["audio"])
    if not include_exports:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["exports"])
    if not include_job_logs:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["job_logs"])

    backup_started_at = datetime.now()
    env_file = ROOT / ".env"
    with tempfile.TemporaryDirectory(prefix="novel-pipeline-backup-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        staging_data_dir = tmp_root_path / "data"
        staging_data_dir.mkdir(parents=True, exist_ok=True)

        copied_files = 0
        total_size = 0
        checksums: list[dict[str, Any]] = []

        for source_path in sorted(source_dir.rglob("*")):
            if source_path.is_dir():
                continue
            relative = source_path.relative_to(source_dir)
            if relative.parts and relative.parts[0] in excluded_roots:
                continue
            if relative.name in {"pipeline.db", "pipeline.db-wal", "pipeline.db-shm"}:
                continue
            destination = staging_data_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            copied_files += 1
            total_size += source_path.stat().st_size
            checksums.append(
                {
                    "path": f"data/{relative.as_posix()}",
                    "sha256": sha256_file(destination),
                    "size_bytes": source_path.stat().st_size,
                }
            )

        live_db_path = source_dir / "pipeline.db"
        db_copy_path = staging_data_dir / "pipeline.db"
        db_exists = live_db_path.exists()
        db_size_bytes = 0
        if db_exists:
            with sqlite3.connect(str(live_db_path)) as src, sqlite3.connect(str(db_copy_path)) as dst:
                src.backup(dst)
            db_size_bytes = db_copy_path.stat().st_size
            copied_files += 1
            total_size += db_size_bytes
            checksums.append(
                {
                    "path": "data/pipeline.db",
                    "sha256": sha256_file(db_copy_path),
                    "size_bytes": db_size_bytes,
                }
            )

        included_modules = [
            "database",
            "uploads",
            "covers",
            "book_assets",
            "glossary_qa",
            "managed_sources",
            "settings",
        ]
        excluded_modules = ["secrets"]
        if include_audio:
            included_modules.append("audio")
        else:
            excluded_modules.append("audio")
        if include_exports:
            included_modules.append("exports")
        else:
            excluded_modules.append("exports")
        if include_job_logs:
            included_modules.append("job_logs")
        else:
            excluded_modules.append("job_logs")
        if include_env and env_file.exists():
            included_modules.append("secrets")
            excluded_modules = [module for module in excluded_modules if module != "secrets"]

        manifest = {
            "app_name": "Novel-TNN Translator",
            "backup_format_version": 2,
            "created_at": backup_started_at.isoformat(timespec="seconds"),
            "app_version": "",
            "project_root_name": ROOT.name,
            "data_directory_name": source_dir.name,
            "included_modules": included_modules,
            "excluded_modules": excluded_modules,
            "file_count": copied_files,
            "total_size_bytes": total_size,
            "database": {
                "filename": "pipeline.db",
                "present": db_exists,
                "size_bytes": db_size_bytes,
            },
            "secrets_included": bool(include_env and env_file.exists()),
            "encrypted": False,
            "checksums": checksums,
        }
        try:
            from app.mobile_api.config import mobile_settings

            manifest["app_version"] = mobile_settings.version
        except Exception:
            manifest["app_version"] = ""

        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        manifest_info.mtime = int(time.time())

        with tarfile.open(backup_path, "w:gz") as archive:
            archive.add(staging_data_dir, arcname="data")
            archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
            env_example = ROOT / ".env.example"
            if env_example.exists():
                archive.add(env_example, arcname=".env.example")
            if include_env and env_file.exists():
                archive.add(env_file, arcname=".env")

        backup_path.with_suffix(backup_path.suffix + BACKUP_MANIFEST_SUFFIX).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if keep is not None:
        rotate_backup_files(destination_dir, keep=keep)

    db_path = source_dir / "pipeline.db"
    if db_path.exists():
        try:
            from app.database.db import record_operational_event

            record_operational_event(
                db_path,
                event_type="backup_success",
                severity="info",
                source="ops",
                message="Backup completed",
                details={"backup_name": backup_path.name, "include_env": include_env},
            )
        except Exception:
            pass

    return backup_path


def encrypt_backup_archive(
    backup_path: Path,
    *,
    passphrase: str,
    iterations: int = 200000,
) -> Path:
    if not passphrase:
        raise ValueError("Backup passphrase is required")
    if not shutil.which("openssl"):
        raise RuntimeError("openssl is required for encrypted backups")
    backup_path = backup_path.resolve()
    encrypted_path = backup_path.with_suffix(backup_path.suffix + ".enc")
    env = {**os.environ, "BACKUP_PASSPHRASE": passphrase}
    subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-salt",
            "-pbkdf2",
            "-iter",
            str(iterations),
            "-in",
            str(backup_path),
            "-out",
            str(encrypted_path),
            "-pass",
            "env:BACKUP_PASSPHRASE",
        ],
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    manifest = read_backup_manifest(backup_path)
    manifest["encrypted"] = True
    manifest["secrets_included"] = True if manifest.get("secrets_included") else False
    encrypted_manifest_path = encrypted_path.with_suffix(encrypted_path.suffix + BACKUP_MANIFEST_SUFFIX)
    encrypted_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    backup_path.unlink(missing_ok=True)
    plain_manifest_path = backup_path.with_suffix(backup_path.suffix + BACKUP_MANIFEST_SUFFIX)
    plain_manifest_path.unlink(missing_ok=True)
    return encrypted_path


def rotate_backup_files(out_dir: Path, *, keep: int) -> list[str]:
    if keep < 1:
        raise ValueError("keep must be >= 1")
    if not out_dir.exists():
        return []

    backup_files: list[Path] = []
    for pattern in BACKUP_GLOB_PATTERNS:
        backup_files.extend(path for path in out_dir.glob(pattern) if path.is_file())
    unique_files = sorted(set(backup_files), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    to_remove = sorted(unique_files[keep:], key=lambda path: (path.stat().st_mtime, path.name))
    removed: list[str] = []
    for path in to_remove:
        path.unlink()
        manifest_path = path.with_suffix(path.suffix + BACKUP_MANIFEST_SUFFIX)
        manifest_path.unlink(missing_ok=True)
        removed.append(str(path))
    return removed


def read_backup_manifest(archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    sidecar_path = archive_path.with_suffix(archive_path.suffix + BACKUP_MANIFEST_SUFFIX)
    if sidecar_path.exists():
        return json.loads(sidecar_path.read_text(encoding="utf-8"))

    if archive_path.name.endswith(".enc"):
        raise FileNotFoundError(f"Missing manifest sidecar for encrypted backup: {archive_path.name}")

    with tarfile.open(archive_path, "r:gz") as archive:
        manifest_member = archive.getmember("manifest.json")
        extracted = archive.extractfile(manifest_member)
        if extracted is None:
            raise FileNotFoundError(f"manifest.json missing in archive: {archive_path.name}")
        return json.loads(extracted.read().decode("utf-8"))


def list_backups(out_dir: Path | None = None) -> list[dict[str, Any]]:
    backup_dir = (out_dir or DEFAULT_BACKUP_DIR).resolve()
    if not backup_dir.exists():
        return []
    backup_files: list[Path] = []
    for pattern in BACKUP_GLOB_PATTERNS:
        backup_files.extend(path for path in backup_dir.glob(pattern) if path.is_file())
    results: list[dict[str, Any]] = []
    for path in sorted(set(backup_files), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            manifest = read_backup_manifest(path)
        except Exception:
            manifest = {}
        results.append(
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "created_at": manifest.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "encrypted": bool(manifest.get("encrypted") or path.name.endswith(".enc")),
                "secrets_included": bool(manifest.get("secrets_included")),
                "included_modules": manifest.get("included_modules", []),
                "excluded_modules": manifest.get("excluded_modules", []),
                "manifest": manifest,
            }
        )
    return results


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    member_path = Path(member.name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"Unsafe archive member path: {member.name}")
    if member.issym() or member.islnk():
        raise ValueError(f"Archive links are not supported: {member.name}")


def restore_backup(archive_path: Path, target_dir: Path | None = None, *, force: bool = False) -> Path:
    archive_path = archive_path.resolve()
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive does not exist: {archive_path}")

    destination = (target_dir or (ROOT / "data_restored")).resolve()
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(
            f"Target directory is not empty: {destination}. Pass --yes to restore into it."
        )
    destination.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_tar_member(member)

        data_members = [
            member
            for member in members
            if member.name == "data" or member.name.startswith("data/")
        ]
        if not data_members:
            raise ValueError("Backup archive does not contain a data/ directory")

        for member in data_members:
            rel = Path(member.name).relative_to("data")
            if str(rel) == ".":
                continue
            target_path = destination / rel
            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with source, target_path.open("wb") as output:
                shutil.copyfileobj(source, output)

    db_path = destination / "pipeline.db"
    if not sqlite_integrity_ok(db_path):
        raise ValueError(f"Restored SQLite database failed integrity check: {db_path}")

    return destination


def restore_drill(
    archive_path: Path,
    *,
    work_dir: Path | None = None,
    passphrase: str | None = None,
    passphrase_env: str = "BACKUP_PASSPHRASE",
) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    encrypted = archive_path.name.endswith(".enc")
    drill_root = (work_dir or Path(tempfile.mkdtemp(prefix="novel-pipeline-restore-drill-"))).resolve()
    drill_root.mkdir(parents=True, exist_ok=True)
    restore_archive = archive_path

    if encrypted:
        resolved_passphrase = passphrase or os.getenv(passphrase_env, "")
        if not resolved_passphrase:
            raise ValueError(f"{passphrase_env} is required for encrypted restore drill")
        if not shutil.which("openssl"):
            raise RuntimeError("openssl is required for encrypted restore drill")
        restore_archive = drill_root / archive_path.name.removesuffix(".enc")
        env = {**os.environ, passphrase_env: resolved_passphrase}
        subprocess.run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-iter",
                os.getenv("OPENSSL_KDF_ITERATIONS", "200000"),
                "-in",
                str(archive_path),
                "-out",
                str(restore_archive),
                "-pass",
                f"env:{passphrase_env}",
            ],
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    target_dir = drill_root / f"restored-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    restored_dir = restore_backup(restore_archive, target_dir)
    db_path = restored_dir / "pipeline.db"
    sqlite_integrity = "ok" if sqlite_integrity_ok(db_path) else "failed"
    if sqlite_integrity != "ok":
        raise ValueError(f"Restore drill SQLite integrity failed: {db_path}")
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        finally:
            conn.close()

    return {
        "ok": True,
        "archive_path": str(archive_path),
        "encrypted": encrypted,
        "restored_dir": str(restored_dir),
        "sqlite_integrity": sqlite_integrity,
    }


def run_doctor(*, json_output: bool = False) -> int:
    os.chdir(ROOT)
    results: list[CheckResult] = []
    results.append(
        CheckResult(
            "python",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    results.append(CheckResult("project_root", (ROOT / "app").exists(), str(ROOT)))

    data_dir = resolve_data_dir()
    try:
        ensure_runtime_dirs(data_dir)
        probe = data_dir / "logs" / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        results.append(CheckResult("data_dir", True, str(data_dir)))
    except Exception as exc:
        results.append(CheckResult("data_dir", False, f"{data_dir}: {exc}"))

    try:
        from app.database.db import init_db

        db_path = data_dir / "pipeline.db"
        init_db(db_path)
        results.append(CheckResult("database", True, str(db_path)))
        results.append(
            CheckResult(
                "database_integrity",
                sqlite_integrity_ok(db_path),
                "ok" if sqlite_integrity_ok(db_path) else "PRAGMA integrity_check failed",
            )
        )
        fk_violations = sqlite_foreign_key_violations(db_path)
        results.append(
            CheckResult(
                "database_foreign_keys",
                not fk_violations,
                "ok"
                if not fk_violations
                else f"{len(fk_violations)} violation(s): {fk_violations[:3]}",
            )
        )
    except Exception as exc:
        results.append(CheckResult("database", False, str(exc)))

    stale_db = data_dir / "novel_pipeline.db"
    if stale_db.exists():
        canonical = data_dir / "pipeline.db"
        message = f"{stale_db} exists; canonical database is {canonical}"
        if stale_db.stat().st_size == 0:
            message = f"empty stale database exists: {stale_db}; canonical database is {canonical}"
        results.append(CheckResult("stale_database", False, message, "warning"))
    else:
        results.append(CheckResult("stale_database", True, "none"))

    try:
        __import__("app.mobile_api.main")

        results.append(CheckResult("mobile_api_import", True, "app.mobile_api.main"))
    except Exception as exc:
        results.append(CheckResult("mobile_api_import", False, str(exc)))

    npm = shutil.which("npm")
    results.append(
        CheckResult(
            "npm",
            bool(npm),
            npm or "npm not found; frontend dev/build commands will be unavailable",
            "warning",
        )
    )
    results.append(
        CheckResult(
            "frontend_package",
            (ROOT / "web" / "package-lock.json").exists(),
            "web/package-lock.json" if (ROOT / "web" / "package-lock.json").exists() else "missing",
            "warning",
        )
    )
    ffmpeg = shutil.which("ffmpeg")
    results.append(
        CheckResult(
            "ffmpeg",
            bool(ffmpeg),
            ffmpeg or "ffmpeg not found; audio merge/export commands will be unavailable",
            "warning",
        )
    )
    provider_keys = [key for key in PROVIDER_KEY_NAMES if os.getenv(key, "").strip()]
    missing_provider_keys = [key for key in PROVIDER_KEY_NAMES if key not in provider_keys]
    results.append(
        CheckResult(
            "provider_keys",
            bool(provider_keys),
            f"{len(provider_keys)} configured"
            + (f"; missing: {', '.join(missing_provider_keys)}" if missing_provider_keys else ""),
            "warning",
        )
    )
    results.append(
        CheckResult(
            "mobile_secret",
            os.getenv("MOBILE_API_SECRET", "") not in {"", "change-this-jwt-secret", "dev-secret-change-in-production"},
            "custom secret configured" if os.getenv("MOBILE_API_SECRET") else "default/dev secret",
            "warning",
        )
    )

    if json_output:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        for result in results:
            status = "OK" if result.ok else ("WARN" if result.severity == "warning" else "FAIL")
            print(f"{status:4} {result.name}: {result.message}")

    return 1 if any(not result.ok and result.severity == "error" for result in results) else 0


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    body = None
    merged_headers = {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc
    return json.loads(data) if data else {}


def _request_status(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> int:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def _request_status_headers(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> tuple[int, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT, **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return int(exc.code), {key.lower(): value for key, value in exc.headers.items()}
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def _request_text(url: str, *, timeout: float = 8.0) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": DEFAULT_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def wait_for_health(base_url: str, *, timeout_seconds: int = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}/api/ready"
    while time.monotonic() < deadline:
        try:
            health = _request_json("GET", health_url, timeout=3.0)
            if health.get("status") == "ok":
                return True
        except Exception:
            time.sleep(1)
    return False


def _fail_if_status_200(path: str, status: int, expected: str) -> None:
    if status == 200:
        raise RuntimeError(f"{path} must be disabled or protected; expected {expected}, got 200")


_PUBLIC_READY_LEAK_MARKERS = (
    "/home/",
    "/tmp/",
    "\\users\\",
    "pipeline.db",
    ".env",
    "data/",
    "backups/",
    "api_key",
    "secret",
    "authorization",
    "bearer ",
    "token",
    "traceback",
)


def _payload_has_public_leak(value: object) -> bool:
    if isinstance(value, dict):
        return any(_payload_has_public_leak(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_payload_has_public_leak(item) for item in value)
    text = str(value).lower()
    return any(marker in text for marker in _PUBLIC_READY_LEAK_MARKERS)


def _require_asset_not_publicly_cacheable(path: str, status: int, headers: dict[str, str]) -> None:
    _fail_if_status_200(path, status, "401/403/404")
    cache_control = headers.get("cache-control", "").lower()
    pragma = headers.get("pragma", "").lower()
    if "no-store" not in cache_control or "private" not in cache_control:
        raise RuntimeError(
            f"{path} must not be publicly cacheable; expected Cache-Control with private, no-store"
        )
    if pragma and "no-cache" not in pragma:
        raise RuntimeError(f"{path} returned unexpected Pragma header: {pragma}")


def _validate_public_cors(base: str) -> None:
    status, headers = _request_status_headers(
        "OPTIONS",
        f"{base}/api/auth/login",
        headers={
            "Origin": base,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    allowed_origin = headers.get("access-control-allow-origin", "")
    if status not in {200, 204} or allowed_origin != base:
        raise RuntimeError(
            f"CORS preflight must allow exactly {base}; got status {status}, "
            f"Access-Control-Allow-Origin={allowed_origin or '<missing>'}"
        )


def run_smoke_public(
    *,
    base_url: str,
    username: str,
    password: str,
    data_probe_path: str = "",
) -> int:
    base = base_url.rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("Public smoke requires an https:// base URL")
    if not username or not password:
        raise RuntimeError("Public smoke requires --username and --password or matching environment values")

    ready = _request_json("GET", f"{base}/api/ready")
    if ready.get("status") != "ok":
        raise RuntimeError(f"/api/ready returned unexpected payload: {ready}")
    if _payload_has_public_leak(ready):
        raise RuntimeError("/api/ready leaks sensitive public diagnostics")
    checks = ready.get("checks") if isinstance(ready.get("checks"), dict) else {}
    if checks and checks.get("public_deploy") is False:
        raise RuntimeError("/api/ready did not report public deploy mode as enabled")
    details = ready.get("details") if isinstance(ready.get("details"), dict) else {}
    if details.get("public_deploy") != "enabled":
        raise RuntimeError("/api/ready did not report public deploy mode as enabled")

    for path in ("/docs", "/openapi.json", "/redoc"):
        status, _headers = _request_status_headers("GET", f"{base}{path}")
        _fail_if_status_200(path, status, "404/401/403")

    _validate_public_cors(base)

    for path in (
        "/covers/__public_smoke_probe__.jpg",
        "/book-assets/__public_smoke_probe__.jpg",
    ):
        status, headers = _request_status_headers("GET", f"{base}{path}")
        _require_asset_not_publicly_cacheable(path, status, headers)

    login = _request_json(
        "POST",
        f"{base}/api/auth/login",
        payload={"username": username, "password": password},
    )
    token = login.get("access_token")
    if not token:
        raise RuntimeError("Login response did not include access_token")

    auth_headers = {"Authorization": f"Bearer {token}"}
    system_status = _request_json("GET", f"{base}/api/system/status", headers=auth_headers)
    if not system_status.get("api_ready"):
        raise RuntimeError(f"/api/system/status did not report api_ready=true: {system_status}")

    if data_probe_path:
        probe_path = "/" + data_probe_path.strip("/")
        probe_status, _headers = _request_status_headers("GET", f"{base}{probe_path}")
        _fail_if_status_200(probe_path, probe_status, "404/401/403")

    print(f"OK public smoke: {base} ready/docs/cors/assets/cache/login/system-status")
    if data_probe_path:
        print(f"OK data probe: /{data_probe_path.strip('/')} is not directly exposed")
    return 0


def run_smoke(
    *,
    base_url: str,
    username: str,
    password: str,
    api_key: str = "",
    web_url: str | None = None,
) -> int:
    base = base_url.rstrip("/")
    headers = {"X-API-Key": api_key} if api_key else {}
    health = _request_json("GET", f"{base}/api/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"Health endpoint returned unexpected payload: {health}")
    ready = _request_json("GET", f"{base}/api/ready")
    if ready.get("status") != "ok":
        raise RuntimeError(f"Readiness endpoint returned unexpected payload: {ready}")

    login = _request_json(
        "POST",
        f"{base}/api/auth/login",
        payload={"username": username, "password": password},
        headers=headers,
    )
    token = login.get("access_token")
    if not token:
        raise RuntimeError("Login response did not include access_token")

    auth_headers = {"Authorization": f"Bearer {token}", **headers}
    providers = _request_json("GET", f"{base}/api/providers", headers=auth_headers)
    if "providers" not in providers:
        raise RuntimeError(f"Providers endpoint returned unexpected payload: {providers}")
    status = _request_json("GET", f"{base}/api/system/status", headers=auth_headers)
    if "data_dir" not in status:
        raise RuntimeError(f"System status returned unexpected payload: {status}")

    if web_url:
        html = _request_text(web_url.rstrip("/") + "/")
        if "<html" not in html.lower() and "<!doctype html" not in html.lower():
            raise RuntimeError("Web endpoint did not return HTML")

    print(f"OK smoke: {base} health/ready/login/providers/system-status")
    if web_url:
        print(f"OK web: {web_url.rstrip('/')}/")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Novel Pipeline operational helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local runtime prerequisites")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable check results")

    backup = subparsers.add_parser("backup", help="Create a timestamped data backup")
    backup.add_argument("--data-dir", type=Path, default=None)
    backup.add_argument("--out-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    backup.add_argument("--include-env", action="store_true", help="Include .env in the archive")
    backup.add_argument("--label", default=None, help="Optional filename suffix")
    backup.add_argument("--keep", type=int, default=None, help="Keep only the newest N local backups after creating one")

    restore = subparsers.add_parser("restore", help="Restore data/ from a backup archive")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--target-dir", type=Path, default=ROOT / "data_restored")
    restore.add_argument("--yes", action="store_true", help="Allow restoring into a non-empty target directory")

    restore_drill_parser = subparsers.add_parser(
        "restore-drill",
        help="Verify a backup can be restored into a temporary drill directory",
    )
    restore_drill_parser.add_argument("archive", type=Path)
    restore_drill_parser.add_argument("--work-dir", type=Path, default=None)
    restore_drill_parser.add_argument(
        "--passphrase-env",
        default="BACKUP_PASSPHRASE",
        help="Environment variable containing the encrypted backup passphrase",
    )

    repair = subparsers.add_parser("repair-db", help="Back up data and repair safe SQLite consistency issues")
    repair.add_argument("--data-dir", type=Path, default=None)
    repair.add_argument("--out-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    repair.add_argument(
        "--remove-empty-stale-db",
        action="store_true",
        help="Delete data/novel_pipeline.db only when it exists and is zero bytes",
    )

    rotate = subparsers.add_parser("rotate-logs", help="Rotate runtime logs under data/logs/runtime")
    rotate.add_argument("--data-dir", type=Path, default=None)
    rotate.add_argument("--max-bytes", type=int, default=1_000_000)
    rotate.add_argument("--keep", type=int, default=5)
    rotate.add_argument("--force", action="store_true")

    provider_key = subparsers.add_parser("set-provider-key", help="Safely store a provider API key in .env")
    provider_key.add_argument("name", choices=PROVIDER_KEY_NAMES)
    source = provider_key.add_mutually_exclusive_group(required=True)
    source.add_argument("--stdin", action="store_true", help="Read the key value from stdin")
    source.add_argument("--from-env", action="store_true", help="Read the key value from the current environment")
    provider_key.add_argument("--env-file", type=Path, default=ROOT / ".env")

    wait = subparsers.add_parser("wait-health", help="Wait until the API readiness endpoint is ok")
    wait.add_argument("--base-url", default="http://127.0.0.1:7860")
    wait.add_argument("--timeout", type=int, default=30)

    smoke = subparsers.add_parser("smoke", help="Run authenticated API and optional web smoke checks")
    smoke.add_argument("--base-url", default="http://127.0.0.1:7860")
    smoke.add_argument("--username", default=os.getenv("MOBILE_API_ADMIN_USERNAME", "admin"))
    smoke.add_argument("--password", default=os.getenv("MOBILE_API_ADMIN_PASSWORD", "change_me"))
    smoke.add_argument(
        "--api-key",
        default="",
        help="Optional extra X-API-Key header for an external proxy; the mobile API itself uses bearer auth",
    )
    smoke.add_argument("--web-url", default=None)

    smoke_public = subparsers.add_parser(
        "smoke-public",
        help="Run non-mutating public deployment smoke checks",
    )
    smoke_public.add_argument("--base-url", required=True)
    smoke_public.add_argument("--username", default=os.getenv("MOBILE_API_ADMIN_USERNAME", ""))
    smoke_public.add_argument("--password", default=os.getenv("MOBILE_API_ADMIN_PASSWORD", ""))
    smoke_public.add_argument(
        "--data-probe-path",
        default=os.getenv("PUBLIC_SMOKE_DATA_PROBE_PATH", ""),
        help="Optional public path that should not return 200, for example data/pipeline.db",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    os.chdir(ROOT)

    if args.command == "doctor":
        return run_doctor(json_output=args.json)
    if args.command == "backup":
        backup_path = create_backup(
            data_dir=args.data_dir,
            out_dir=args.out_dir,
            include_env=args.include_env,
            label=args.label,
            keep=args.keep,
        )
        print(backup_path)
        return 0
    if args.command == "restore":
        restored_dir = restore_backup(args.archive, args.target_dir, force=args.yes)
        print(restored_dir)
        return 0
    if args.command == "restore-drill":
        result = restore_drill(
            args.archive,
            work_dir=args.work_dir,
            passphrase_env=args.passphrase_env,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "repair-db":
        result = repair_database(
            data_dir=args.data_dir,
            out_dir=args.out_dir,
            remove_empty_stale_db=args.remove_empty_stale_db,
        )
        print(json.dumps(result, indent=2))
        return 1 if result["remaining_fk_violations"] else 0
    if args.command == "rotate-logs":
        rotated = rotate_runtime_logs(
            data_dir=args.data_dir,
            max_bytes=args.max_bytes,
            keep=args.keep,
            force=args.force,
        )
        print(json.dumps({"rotated": rotated}, indent=2))
        return 0
    if args.command == "set-provider-key":
        value = os.getenv(args.name, "") if args.from_env else sys.stdin.read()
        update_env_file_value(args.env_file, args.name, value)
        print(f"{args.name} configured in {args.env_file} (len={len(value.strip())})")
        return 0
    if args.command == "wait-health":
        if wait_for_health(args.base_url, timeout_seconds=args.timeout):
            print(f"OK ready: {args.base_url.rstrip('/')}/api/ready")
            return 0
        print(f"FAIL readiness timeout: {args.base_url.rstrip('/')}/api/ready", file=sys.stderr)
        return 1
    if args.command == "smoke":
        return run_smoke(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            api_key=args.api_key,
            web_url=args.web_url,
        )
    if args.command == "smoke-public":
        try:
            return run_smoke_public(
                base_url=args.base_url,
                username=args.username,
                password=args.password,
                data_probe_path=args.data_probe_path,
            )
        except RuntimeError as exc:
            print(f"FAIL public smoke: {exc}", file=sys.stderr)
            return 1

    parser.error(f"Unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
