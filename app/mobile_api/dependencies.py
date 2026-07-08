from __future__ import annotations

from pathlib import Path

from app.config import settings


def get_data_dir() -> Path:
    data_dir = settings.resolved_data_dir
    for sub in (
        "raw",
        "cleaned",
        "translated",
        "audio",
        "exports",
        "glossary",
        "logs",
        "covers",
        "book_assets",
        "dictionaries",
    ):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    return get_data_dir() / "pipeline.db"
