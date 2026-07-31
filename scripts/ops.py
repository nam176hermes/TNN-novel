#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import hashlib
import json
import os
import re
import secrets
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
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_BACKUP_DIR = ROOT / "backups"
RUNTIME_SUBDIRS = ("raw", "cleaned", "translated", "audio", "exports", "glossary", "logs")
DEFAULT_USER_AGENT = "novel-pipeline-smoke/1.0"
PROVIDER_KEY_NAMES = ("GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
BACKUP_GLOB_PATTERNS = ("novel-pipeline-backup-*.tar.gz", "novel-pipeline-backup-*.tar.gz.enc")
BACKUP_MANIFEST_SUFFIX = ".manifest.json"
BACKUP_SIDECAR_SCHEMA_VERSION = 1
# P1A_FIX_APPLIED: normal backup listing consumes bounded sidecar/stat metadata only.
MAX_BACKUP_SIDECAR_BYTES = 8 * 1024 * 1024
MAX_INTERNAL_BACKUP_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_BACKUP_ARCHIVE_MEMBERS = 1_000_000
MAX_BACKUP_METADATA_STRING = 512
MAX_BACKUP_METADATA_MODULES = 64
SAFE_MANIFEST_FIELDS = {
    "app_name",
    "app_version",
    "artifact_state",
    "archive_checksum",
    "archive_size_bytes",
    "backup_filename",
    "backup_format_version",
    "created_at",
    "encrypted",
    "excluded_modules",
    "file_count",
    "included_modules",
    "manifest_version",
    "secrets_included",
    "sidecar_schema_version",
    "total_size_bytes",
}
_SAFE_MODULE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SAFE_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
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


class BackupCancelled(RuntimeError):
    pass


def _raise_if_backup_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise BackupCancelled("Backup creation was cancelled")


def _notify_backup_progress(callback: Callable[[str], None] | None, step: str) -> None:
    if callback is not None:
        callback(step)


def _backup_staging_path(out_dir: Path, final_name: str) -> Path:
    staging_path = out_dir / f".{final_name}.partial"
    staging_path.mkdir(mode=0o700, exist_ok=False)
    try:
        staging_path.chmod(0o700)
    except Exception:
        shutil.rmtree(staging_path)
        raise
    return staging_path


def _backup_collision_name(base_name: str) -> str:
    for extension in (".tar.gz.enc", ".tar.gz"):
        if base_name.endswith(extension):
            stem = base_name.removesuffix(extension)
            return f"{stem}-{secrets.token_hex(6)}{extension}"
    raise ValueError("unsupported backup filename")


def _reserve_backup_output(out_dir: Path, base_name: str) -> tuple[Path, Path]:
    candidate = base_name
    while True:
        final_path = out_dir / candidate
        sidecar_path = backup_sidecar_path(final_path)
        if os.path.lexists(final_path) or os.path.lexists(sidecar_path):
            candidate = _backup_collision_name(base_name)
            continue
        try:
            staging_path = _backup_staging_path(out_dir, candidate)
        except FileExistsError:
            candidate = _backup_collision_name(base_name)
            continue
        if os.path.lexists(final_path) or os.path.lexists(sidecar_path):
            shutil.rmtree(staging_path)
            candidate = _backup_collision_name(base_name)
            continue
        return final_path, staging_path


def _publish_backup_file(source: Path, destination: Path) -> None:
    os.link(source, destination)
    source.unlink()


def _cleanup_owned_backup_staging_best_effort(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except Exception:
        # Owned hidden residue remains outside normal list/download paths. A
        # cleanup failure must not overturn publication or mask its root cause.
        pass


def _validate_backup_archive(archive_path: Path) -> dict[str, Any]:
    return _inspect_plain_backup_archive(archive_path)


def _fsync_backup_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


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
    record_event: bool = True,
    checkpoint_database: bool = True,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    _notify_backup_progress(progress_callback, "preparing")
    _raise_if_backup_cancelled(cancel_check)
    source_dir = (data_dir or resolve_data_dir()).resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {source_dir}")

    destination_dir = (out_dir or DEFAULT_BACKUP_DIR).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    if checkpoint_database:
        sqlite_checkpoint(source_dir / "pipeline.db")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""

    excluded_roots: set[str] = set()
    if not include_audio:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["audio"])
    if not include_exports:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["exports"])
    if not include_job_logs:
        excluded_roots.update(BACKUP_MODULE_SUBDIRS["job_logs"])

    backup_started_at = datetime.now()
    env_file = ROOT / ".env"
    backup_path, staging_root = _reserve_backup_output(
        destination_dir,
        f"novel-pipeline-backup-{stamp}{suffix}.tar.gz",
    )
    staging_data_dir = staging_root / "data"
    staged_archive_path = staging_root / backup_path.name
    staged_sidecar_path = backup_sidecar_path(staged_archive_path)
    try:
        staging_data_dir.mkdir(parents=True, exist_ok=True)

        copied_files = 0
        total_size = 0
        checksums: list[dict[str, Any]] = []

        _notify_backup_progress(progress_callback, "collecting")
        for source_path in sorted(source_dir.rglob("*")):
            if source_path.is_dir():
                continue
            relative = source_path.relative_to(source_dir)
            if relative.parts and relative.parts[0] in excluded_roots:
                continue
            if relative.name in {"pipeline.db", "pipeline.db-wal", "pipeline.db-shm"}:
                continue
            _raise_if_backup_cancelled(cancel_check)
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
            _raise_if_backup_cancelled(cancel_check)
            live_db_uri = f"file:{live_db_path.resolve()}?mode=ro"
            with sqlite3.connect(live_db_uri, uri=True) as src, sqlite3.connect(str(db_copy_path)) as dst:
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

        _notify_backup_progress(progress_callback, "writing")
        _raise_if_backup_cancelled(cancel_check)
        with tarfile.open(staged_archive_path, "w:gz") as archive:
            archive.add(staging_data_dir, arcname="data", recursive=False)
            for staged_path in sorted(staging_data_dir.rglob("*")):
                _raise_if_backup_cancelled(cancel_check)
                relative = staged_path.relative_to(staging_data_dir)
                archive.add(
                    staged_path,
                    arcname=f"data/{relative.as_posix()}",
                    recursive=False,
                )
            _raise_if_backup_cancelled(cancel_check)
            archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
            env_example = ROOT / ".env.example"
            if env_example.exists():
                _raise_if_backup_cancelled(cancel_check)
                archive.add(env_example, arcname=".env.example", recursive=False)
            if include_env and env_file.exists():
                _raise_if_backup_cancelled(cancel_check)
                archive.add(env_file, arcname=".env", recursive=False)

        _fsync_backup_file(staged_archive_path)
        _notify_backup_progress(progress_callback, "validating")
        _raise_if_backup_cancelled(cancel_check)
        _validate_backup_archive(staged_archive_path)
        write_backup_sidecar_atomic(
            staged_archive_path,
            build_backup_sidecar(manifest, staged_archive_path),
        )

        _notify_backup_progress(progress_callback, "publishing")
        _raise_if_backup_cancelled(cancel_check)
        _publish_backup_file(staged_archive_path, backup_path)
        _publish_backup_file(staged_sidecar_path, backup_sidecar_path(backup_path))
    finally:
        shutil.rmtree(staging_root)

    if keep is not None:
        rotate_backup_files(destination_dir, keep=keep)

    db_path = source_dir / "pipeline.db"
    if record_event and db_path.exists():
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
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    if not passphrase:
        raise ValueError("Backup passphrase is required")
    if not shutil.which("openssl"):
        raise RuntimeError("openssl is required for encrypted backups")
    backup_path = backup_path.resolve()
    manifest = read_backup_manifest(backup_path)
    encrypted_path, staging_root = _reserve_backup_output(
        backup_path.parent,
        f"{backup_path.name}.enc",
    )
    staged_encrypted_path = staging_root / encrypted_path.name
    staged_sidecar_path = backup_sidecar_path(staged_encrypted_path)
    try:
        _notify_backup_progress(progress_callback, "encrypting")
        _raise_if_backup_cancelled(cancel_check)
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
                str(staged_encrypted_path),
                "-pass",
                "env:BACKUP_PASSPHRASE",
            ],
            check=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _fsync_backup_file(staged_encrypted_path)
        _raise_if_backup_cancelled(cancel_check)
        manifest["encrypted"] = True
        manifest["secrets_included"] = bool(manifest.get("secrets_included"))
        write_backup_sidecar_atomic(
            staged_encrypted_path,
            build_backup_sidecar(manifest, staged_encrypted_path),
        )
        _notify_backup_progress(progress_callback, "publishing")
        _raise_if_backup_cancelled(cancel_check)
        _publish_backup_file(staged_encrypted_path, encrypted_path)
        _publish_backup_file(staged_sidecar_path, backup_sidecar_path(encrypted_path))
    finally:
        shutil.rmtree(staging_root)

    backup_path.unlink(missing_ok=True)
    plain_manifest_path = backup_path.with_suffix(backup_path.suffix + BACKUP_MANIFEST_SUFFIX)
    plain_manifest_path.unlink(missing_ok=True)
    return encrypted_path


def _publish_ready_encrypted_backup(archive_path: Path, out_dir: Path) -> Path:
    """Publish a validated encrypted artifact pair without exposing a bare archive."""
    archive_path = archive_path.resolve()
    metadata = read_backup_sidecar(archive_path)
    if not archive_path.name.endswith(".tar.gz.enc") or not metadata.get("encrypted"):
        raise ValueError("encrypted READY backup is required")
    if metadata.get("artifact_state") != "READY":
        raise ValueError("encrypted backup metadata is not READY")

    destination_dir = out_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    final_path, staging_root = _reserve_backup_output(destination_dir, archive_path.name)
    staged_archive_path = staging_root / final_path.name
    staged_sidecar_path = backup_sidecar_path(staged_archive_path)
    published_sidecar = False
    published_archive = False
    try:
        os.link(archive_path, staged_archive_path)
        _fsync_backup_file(staged_archive_path)
        write_backup_sidecar_atomic(
            staged_archive_path,
            build_backup_sidecar(metadata, staged_archive_path),
        )
        # Sidecar-first publication ensures a directly-addressable archive is never
        # present without READY metadata. Roll back either link on any failure.
        final_sidecar_path = backup_sidecar_path(final_path)
        os.link(staged_sidecar_path, final_sidecar_path)
        published_sidecar = True
        staged_sidecar_path.unlink()
        os.link(staged_archive_path, final_path)
        published_archive = True
        staged_archive_path.unlink()
        return final_path
    except Exception:
        if published_archive:
            final_path.unlink(missing_ok=True)
        if published_sidecar:
            backup_sidecar_path(final_path).unlink(missing_ok=True)
        raise
    finally:
        _cleanup_owned_backup_staging_best_effort(staging_root)


def create_encrypted_backup(
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    *,
    passphrase: str,
    include_audio: bool = True,
    include_exports: bool = False,
    include_job_logs: bool = False,
    label: str | None = None,
    keep: int | None = None,
    record_event: bool = True,
    checkpoint_database: bool = True,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Create a secret-bearing backup without publishing plaintext metadata or bytes."""
    if not passphrase.strip():
        raise ValueError("Backup passphrase is required")
    source_dir = (data_dir or resolve_data_dir()).resolve()
    destination_dir = (out_dir or DEFAULT_BACKUP_DIR).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    private_root = _backup_staging_path(
        destination_dir,
        f"novel-pipeline-secret-backup-{secrets.token_hex(8)}",
    )
    try:
        plain_path = create_backup(
            data_dir=source_dir,
            out_dir=private_root,
            include_env=True,
            include_audio=include_audio,
            include_exports=include_exports,
            include_job_logs=include_job_logs,
            label=label,
            record_event=False,
            checkpoint_database=checkpoint_database,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        encrypted_path = encrypt_backup_archive(
            plain_path,
            passphrase=passphrase.strip(),
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        _raise_if_backup_cancelled(cancel_check)
        published_path = _publish_ready_encrypted_backup(encrypted_path, destination_dir)
    finally:
        _cleanup_owned_backup_staging_best_effort(private_root)

    if keep is not None:
        rotate_backup_files(destination_dir, keep=keep)

    db_path = source_dir / "pipeline.db"
    if record_event and db_path.exists():
        try:
            from app.database.db import record_operational_event

            record_operational_event(
                db_path,
                event_type="backup_success",
                severity="info",
                source="ops",
                message="Backup completed",
                details={"backup_name": published_path.name, "include_env": True},
            )
        except Exception:
            pass
    return published_path


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


def backup_sidecar_path(archive_path: Path) -> Path:
    return archive_path.with_suffix(archive_path.suffix + BACKUP_MANIFEST_SUFFIX)


def build_backup_sidecar(manifest: dict[str, Any], archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    stat = archive_path.lstat()
    if archive_path.is_symlink() or not archive_path.is_file() or stat.st_size <= 0:
        raise ValueError("backup artifact must be a regular non-empty file")
    metadata: dict[str, Any] = {
        "sidecar_schema_version": BACKUP_SIDECAR_SCHEMA_VERSION,
        "manifest_version": str(manifest.get("backup_format_version", "")),
        "backup_filename": archive_path.name,
        "backup_format_version": int(manifest.get("backup_format_version", 0)),
        "created_at": str(manifest.get("created_at", "")),
        "archive_size_bytes": stat.st_size,
        "encrypted": bool(manifest.get("encrypted") or archive_path.name.endswith(".enc")),
        "secrets_included": bool(manifest.get("secrets_included")),
        "included_modules": list(manifest.get("included_modules", [])),
        "excluded_modules": list(manifest.get("excluded_modules", [])),
        "file_count": int(manifest.get("file_count", 0)),
        "total_size_bytes": int(manifest.get("total_size_bytes", 0)),
        "app_version": str(manifest.get("app_version", "")),
        "artifact_state": "READY",
    }
    if manifest.get("archive_checksum"):
        metadata["archive_checksum"] = str(manifest["archive_checksum"])
    return _safe_manifest_summary(metadata)


def write_backup_sidecar_atomic(archive_path: Path, metadata: dict[str, Any]) -> Path:
    archive_path = archive_path.resolve()
    sidecar_path = backup_sidecar_path(archive_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{sidecar_path.name}.",
        suffix=".tmp",
        dir=sidecar_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, sidecar_path)
        return sidecar_path
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _bounded_string(value: Any, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_BACKUP_METADATA_STRING:
        raise ValueError(f"invalid {field}")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"invalid {field}")
    if (
        Path(value).is_absolute()
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith("\\\\")
        or re.search(r"(?:^|[\s=:])/(?:[^/\s]+/)+", value)
    ):
        raise ValueError(f"invalid {field}")
    return value


def _bounded_nonnegative_int(value: Any, *, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid {field}")
    return value


def _bounded_bool(value: Any, *, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"invalid {field}")
    return value


def _bounded_modules(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_BACKUP_METADATA_MODULES:
        raise ValueError(f"invalid {field}")
    modules: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SAFE_MODULE_RE.fullmatch(item):
            raise ValueError(f"invalid {field}")
        modules.append(item)
    return modules


def _safe_manifest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field in SAFE_MANIFEST_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if field in {"encrypted", "secrets_included"}:
            summary[field] = _bounded_bool(value, field=field)
        elif field in {
            "archive_size_bytes",
            "backup_format_version",
            "file_count",
            "sidecar_schema_version",
            "total_size_bytes",
        }:
            summary[field] = _bounded_nonnegative_int(value, field=field)
        elif field in {"included_modules", "excluded_modules"}:
            summary[field] = _bounded_modules(value, field=field)
        else:
            summary[field] = _bounded_string(value, field=field)
    return summary


def read_backup_sidecar(archive_path: Path) -> dict[str, Any]:
    sidecar_path = backup_sidecar_path(archive_path)
    stat = sidecar_path.lstat()
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise ValueError("invalid backup sidecar")
    if stat.st_size <= 0 or stat.st_size > MAX_BACKUP_SIDECAR_BYTES:
        raise ValueError("invalid backup sidecar")
    with sidecar_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("backup sidecar must be an object")
    summary = _safe_manifest_summary(payload)
    backup_filename = summary.get("backup_filename")
    if backup_filename and backup_filename != archive_path.name:
        raise ValueError("backup sidecar filename does not match artifact")
    return summary


def read_backup_manifest(archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    sidecar_path = backup_sidecar_path(archive_path)
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


def _is_supported_backup_name(name: str) -> bool:
    return name.startswith("novel-pipeline-backup-") and (
        name.endswith(".tar.gz") or name.endswith(".tar.gz.enc")
    )


def _backup_listing_item(
    *,
    filename: str,
    size_bytes: int,
    created_at: str,
    encrypted: bool,
    status: str,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_manifest = manifest or {}
    warnings = {
        "METADATA_MISSING": "Backup metadata is missing. Run the explicit metadata repair command.",
        "METADATA_INVALID": "Backup metadata is invalid. Run the explicit metadata repair command.",
        "ARTIFACT_MISSING": "Backup artifact is missing.",
        "ARTIFACT_INVALID": "Backup artifact is not a valid regular non-empty file.",
        "UNSUPPORTED_FORMAT": "Backup format is not supported.",
    }
    return {
        "filename": filename,
        "size_bytes": size_bytes,
        "created_at": safe_manifest.get("created_at") or created_at,
        "encrypted": bool(safe_manifest.get("encrypted", encrypted)),
        "secrets_included": bool(safe_manifest.get("secrets_included", False)),
        "included_modules": list(safe_manifest.get("included_modules", [])),
        "excluded_modules": list(safe_manifest.get("excluded_modules", [])),
        "manifest": safe_manifest,
        "metadata_status": status,
        "repair_needed": status in {"METADATA_MISSING", "METADATA_INVALID"},
        "manifest_available": status == "READY",
        "archive_available": status in {"READY", "METADATA_MISSING", "METADATA_INVALID"},
        "warning": warnings.get(status, ""),
    }


def list_backups(out_dir: Path | None = None) -> list[dict[str, Any]]:
    backup_dir = (out_dir or DEFAULT_BACKUP_DIR).resolve()
    if not backup_dir.exists():
        return []
    entries = list(backup_dir.iterdir())
    archive_paths: dict[str, Path] = {
        path.name: path for path in entries if _is_supported_backup_name(path.name)
    }
    orphan_names: set[str] = set()
    pending_sidecar_names: set[str] = set()
    for path in entries:
        if not path.name.endswith(BACKUP_MANIFEST_SUFFIX):
            continue
        archive_name = path.name.removesuffix(BACKUP_MANIFEST_SUFFIX)
        pending_publication = backup_dir / f".{archive_name}.partial"
        if pending_publication.is_dir() and not pending_publication.is_symlink():
            # A sidecar-first encrypted publication may be interrupted before
            # its archive link. The private reservation marks that orphan as
            # incomplete so restart-time listing cannot expose it as a backup.
            pending_sidecar_names.add(path.name)
            continue
        if _is_supported_backup_name(archive_name) and archive_name not in archive_paths:
            orphan_names.add(archive_name)

    results: list[dict[str, Any]] = []
    for name, path in archive_paths.items():
        encrypted = name.endswith(".enc")
        try:
            stat = path.lstat()
        except OSError:
            results.append(_backup_listing_item(
                filename=name, size_bytes=0, created_at="", encrypted=encrypted, status="ARTIFACT_INVALID"
            ))
            continue
        created_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        if path.is_symlink() or not path.is_file() or stat.st_size <= 0:
            results.append(_backup_listing_item(
                filename=name,
                size_bytes=max(0, stat.st_size),
                created_at=created_at,
                encrypted=encrypted,
                status="ARTIFACT_INVALID",
            ))
            continue
        sidecar = backup_sidecar_path(path)
        if not sidecar.exists() and not sidecar.is_symlink():
            results.append(_backup_listing_item(
                filename=name,
                size_bytes=stat.st_size,
                created_at=created_at,
                encrypted=encrypted,
                status="METADATA_MISSING",
            ))
            continue
        try:
            manifest = read_backup_sidecar(path)
            status = "READY"
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            manifest = {}
            status = "METADATA_INVALID"
        results.append(_backup_listing_item(
            filename=name,
            size_bytes=stat.st_size,
            created_at=created_at,
            encrypted=encrypted,
            status=status,
            manifest=manifest,
        ))

    for name in orphan_names:
        sidecar = backup_dir / f"{name}{BACKUP_MANIFEST_SUFFIX}"
        try:
            created_at = datetime.fromtimestamp(sidecar.lstat().st_mtime).isoformat()
        except OSError:
            created_at = ""
        results.append(_backup_listing_item(
            filename=name,
            size_bytes=0,
            created_at=created_at,
            encrypted=name.endswith(".enc"),
            status="ARTIFACT_MISSING",
        ))

    supported_names = set(archive_paths)
    sidecar_names = {
        f"{name}{BACKUP_MANIFEST_SUFFIX}" for name in supported_names | orphan_names
    } | pending_sidecar_names
    for path in entries:
        if path.name in supported_names or path.name in sidecar_names:
            continue
        if ".partial" in path.name or path.name.endswith(".tmp"):
            continue
        if path.name.startswith("novel-pipeline-backup-"):
            try:
                stat = path.lstat()
                size_bytes = max(0, stat.st_size)
                created_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                size_bytes = 0
                created_at = ""
            results.append(_backup_listing_item(
                filename=path.name,
                size_bytes=size_bytes,
                created_at=created_at,
                encrypted=False,
                status="UNSUPPORTED_FORMAT",
            ))

    return sorted(results, key=lambda item: (item["created_at"], item["filename"]), reverse=True)


def _derive_legacy_backup_manifest(
    archive_path: Path,
    members: list[tarfile.TarInfo],
) -> dict[str, Any]:
    if len(members) > MAX_BACKUP_ARCHIVE_MEMBERS:
        raise ValueError("backup archive has too many members")
    for member in members:
        _validate_tar_member(member)

    data_files = [
        member
        for member in members
        if member.isreg() and member.name.startswith("data/")
    ]
    if not data_files:
        raise ValueError("backup archive does not contain data files")

    names = {member.name for member in members}
    included_modules: list[str] = []
    module_prefixes = (
        ("database", ("data/pipeline.db", "data/novel_pipeline.db")),
        ("uploads", ("data/raw/", "data/cleaned/", "data/translated/", "data/inbox/")),
        ("covers", ("data/covers/",)),
        ("book_assets", ("data/book_assets/",)),
        ("audio", ("data/audio/",)),
        ("exports", ("data/exports/",)),
        ("job_logs", ("data/logs/",)),
        ("glossary_qa", ("data/glossary/",)),
    )
    for module, prefixes in module_prefixes:
        if any(name == prefix or name.startswith(prefix) for name in names for prefix in prefixes):
            included_modules.append(module)

    secrets_included = ".env" in names
    return {
        "app_name": "Novel-TNN Translator",
        "backup_format_version": 1,
        "created_at": datetime.fromtimestamp(archive_path.stat().st_mtime).isoformat(timespec="seconds"),
        "app_version": "",
        "included_modules": included_modules,
        "excluded_modules": [] if secrets_included else ["secrets"],
        "file_count": len(data_files),
        "total_size_bytes": sum(member.size for member in data_files),
        "secrets_included": secrets_included,
        "encrypted": False,
    }


def _inspect_plain_backup_archive(archive_path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_BACKUP_ARCHIVE_MEMBERS:
                raise ValueError("backup archive has too many members")
            for current in members:
                _validate_tar_member(current)
            member = next((current for current in members if current.name == "manifest.json"), None)
            if member is None:
                return _derive_legacy_backup_manifest(archive_path, members)
            if not member.isreg() or member.size <= 0 or member.size > MAX_INTERNAL_BACKUP_MANIFEST_BYTES:
                raise ValueError("invalid internal backup manifest")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError("invalid internal backup manifest")
            payload_bytes = extracted.read(MAX_INTERNAL_BACKUP_MANIFEST_BYTES + 1)
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("backup archive metadata inspection failed") from exc
    if len(payload_bytes) > MAX_INTERNAL_BACKUP_MANIFEST_BYTES:
        raise ValueError("invalid internal backup manifest")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid internal backup manifest") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid internal backup manifest")
    return payload


def inspect_backup_archive_explicitly(
    archive_path: Path,
    *,
    passphrase_env: str = "BACKUP_PASSPHRASE",
) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    if not archive_path.exists() or not archive_path.is_file() or archive_path.stat().st_size <= 0:
        raise ValueError("backup artifact is unavailable")
    if not archive_path.name.endswith(".enc"):
        return _inspect_plain_backup_archive(archive_path)

    if not _SAFE_ENV_NAME_RE.fullmatch(passphrase_env):
        raise ValueError("invalid environment variable name")
    secret = os.getenv(passphrase_env, "")
    if not secret:
        raise ValueError("encrypted backup metadata is unavailable")
    if not shutil.which("openssl"):
        raise RuntimeError("encrypted backup metadata inspection is unavailable")
    with tempfile.TemporaryDirectory(prefix="novel-pipeline-backup-inspect-") as tmp_root:
        decrypted = Path(tmp_root) / archive_path.name.removesuffix(".enc")
        env = {**os.environ, passphrase_env: secret}
        try:
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
                    str(decrypted),
                    "-pass",
                    f"env:{passphrase_env}",
                ],
                check=True,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError("encrypted backup metadata inspection failed") from exc
        return _inspect_plain_backup_archive(decrypted)


def _write_safe_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def repair_backup_metadata(
    backup_dir: Path,
    *,
    filename: str | None,
    all_missing: bool,
    apply: bool,
    overwrite: bool,
    passphrase_env: str,
    report_dir: Path | None,
) -> dict[str, Any]:
    if bool(filename) == bool(all_missing):
        raise ValueError("select exactly one filename or all missing metadata")
    backup_dir = backup_dir.resolve()
    if not backup_dir.exists() or not backup_dir.is_dir():
        raise ValueError("backup directory is unavailable")

    if filename:
        if Path(filename).name != filename or not _is_supported_backup_name(filename):
            raise ValueError("invalid backup filename")
        selected_names = [filename]
    else:
        selected_names = [
            item["filename"]
            for item in list_backups(backup_dir)
            if item["metadata_status"] in {"METADATA_MISSING", "METADATA_INVALID"}
        ]

    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "selected": len(selected_names),
        "would_write": 0,
        "written": 0,
        "skipped_valid": 0,
        "failed": 0,
        "entries": [],
    }
    for name in selected_names:
        archive = backup_dir / name
        sidecar = backup_sidecar_path(archive)
        if not archive.exists() or archive.is_symlink() or not archive.is_file():
            report["failed"] += 1
            report["entries"].append({"filename": name, "result": "FAILED", "warning": "Backup artifact is unavailable."})
            continue
        if sidecar.exists() and not overwrite:
            try:
                read_backup_sidecar(archive)
            except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                report["skipped_valid"] += 1
                report["entries"].append({"filename": name, "result": "SKIPPED_VALID", "warning": ""})
                continue
        try:
            manifest = inspect_backup_archive_explicitly(archive, passphrase_env=passphrase_env)
            metadata = build_backup_sidecar(manifest, archive)
        except (OSError, RuntimeError, ValueError):
            report["failed"] += 1
            report["entries"].append({"filename": name, "result": "FAILED", "warning": "Backup metadata could not be inspected."})
            continue
        report["would_write"] += 1
        if apply:
            write_backup_sidecar_atomic(archive, metadata)
            report["written"] += 1
            result = "WRITTEN"
        else:
            result = "WOULD_WRITE"
        report["entries"].append({"filename": name, "result": result, "warning": ""})

    if report_dir is not None:
        report_path = report_dir.resolve() / "backup-metadata-repair.json"
        _write_safe_json_atomic(report_path, report)
    return report


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
    exposed_path_fields = {"database_path", "data_dir"}.intersection(status)
    if exposed_path_fields:
        raise RuntimeError(f"System status exposed absolute path fields: {sorted(exposed_path_fields)}")
    required_status_fields = {"database_available", "data_directory_available", "storage_health"}
    if not required_status_fields.issubset(status):
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
    backup.add_argument(
        "--no-record-event",
        action="store_true",
        help="Do not write a backup event to the source database",
    )
    backup.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Do not checkpoint the source WAL before the SQLite backup API copy",
    )

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

    metadata_repair = subparsers.add_parser(
        "backup-metadata-repair",
        help="Inspect backups explicitly and repair compact metadata sidecars",
    )
    metadata_repair.add_argument("--backup-dir", type=Path, required=True)
    metadata_selection = metadata_repair.add_mutually_exclusive_group(required=True)
    metadata_selection.add_argument("--filename")
    metadata_selection.add_argument("--all-missing", action="store_true")
    metadata_mode = metadata_repair.add_mutually_exclusive_group()
    metadata_mode.add_argument("--dry-run", action="store_true")
    metadata_mode.add_argument("--apply", action="store_true")
    metadata_repair.add_argument("--overwrite", action="store_true")
    metadata_repair.add_argument("--passphrase-env", default="BACKUP_PASSPHRASE")
    metadata_repair.add_argument("--report-dir", type=Path, default=None)

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
            record_event=not args.no_record_event,
            checkpoint_database=not args.no_checkpoint,
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
    if args.command == "backup-metadata-repair":
        result = repair_backup_metadata(
            args.backup_dir,
            filename=args.filename,
            all_missing=args.all_missing,
            apply=args.apply,
            overwrite=args.overwrite,
            passphrase_env=args.passphrase_env,
            report_dir=args.report_dir,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result["failed"] else 0
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
