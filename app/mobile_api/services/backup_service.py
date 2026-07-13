from __future__ import annotations

from pathlib import Path

from app.mobile_api.dependencies import get_data_dir
from scripts import ops


class BackupService:
    def __init__(self, backup_dir: Path | None = None, data_dir: Path | None = None):
        self.backup_dir = (backup_dir or ops.DEFAULT_BACKUP_DIR).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = (data_dir or get_data_dir()).resolve()

    def list_backups(self) -> list[dict]:
        items = ops.list_backups(self.backup_dir)
        for item in items:
            item["download_url"] = (
                f"/api/system/backups/{item['filename']}/download"
                if item.get("metadata_status") == "READY"
                else ""
            )
        return items

    def create_backup(
        self,
        *,
        include_audio: bool = True,
        include_exports: bool = False,
        include_job_logs: bool = False,
        include_secrets: bool = False,
        passphrase: str = "",
    ) -> dict:
        if include_secrets and not passphrase.strip():
            raise ValueError("Encrypted backup passphrase is required when secrets are included")

        backup_path = ops.create_backup(
            data_dir=self.data_dir,
            include_env=include_secrets,
            include_audio=include_audio,
            include_exports=include_exports,
            include_job_logs=include_job_logs,
            out_dir=self.backup_dir,
        )
        if include_secrets:
            backup_path = ops.encrypt_backup_archive(backup_path, passphrase=passphrase.strip())

        backups = self.list_backups()
        for item in backups:
            if item["filename"] == backup_path.name and item.get("metadata_status") == "READY":
                return item
        raise FileNotFoundError(f"Backup metadata missing for {backup_path.name}")

    def resolve_download_path(self, filename: str) -> Path:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError("Invalid backup filename")
        path = (self.backup_dir / filename).resolve()
        if self.backup_dir not in path.parents or not path.exists() or not path.is_file():
            raise FileNotFoundError("Backup not found")
        return path
