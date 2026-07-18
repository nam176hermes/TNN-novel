from __future__ import annotations

import sqlite3
from pathlib import Path


def _restrict_database_file_permissions(db_path: Path) -> None:
    """Keep a SQLite database and its sidecars private to the service group."""
    for path in (db_path, db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm")):
        try:
            if path.is_file():
                path.chmod(0o660)
        except OSError:
            # Development mounts without POSIX permissions must remain usable.
            continue


class _PrivateSQLiteConnection(sqlite3.Connection):
    """Normalize SQLite file permissions after transaction boundaries."""

    def __init__(self, database: str, *args: object, **kwargs: object) -> None:
        self._database_path = Path(database)
        super().__init__(database, *args, **kwargs)
        _restrict_database_file_permissions(self._database_path)

    def __exit__(self, *args: object) -> bool:
        try:
            return super().__exit__(*args)
        finally:
            _restrict_database_file_permissions(self._database_path)

    def close(self) -> None:
        try:
            super().close()
        finally:
            _restrict_database_file_permissions(self._database_path)


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), factory=_PrivateSQLiteConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
