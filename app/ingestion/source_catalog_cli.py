from __future__ import annotations

import argparse
from pathlib import Path

from app.config import settings
from app.database.db import init_db
from app.ingestion.source_catalog import import_source_catalog_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a local Novela/yckceo source catalog JSON into Novel-TNN metadata storage."
    )
    parser.add_argument("catalog_json", type=Path, help="Path to yckceo_sources.json or compatible JSON list")
    parser.add_argument(
        "--catalog-source",
        default="yckceo",
        help="Catalog source label. Supported values are yckceo/novela; defaults to yckceo.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=settings.db_path,
        help=f"SQLite database path. Defaults to {settings.db_path}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog_path = args.catalog_json.expanduser().resolve()
    db_path = args.db_path.expanduser().resolve()
    if not catalog_path.exists():
        raise SystemExit(f"Catalog JSON not found: {catalog_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    result = import_source_catalog_json(
        db_path,
        catalog_path,
        catalog_source=args.catalog_source,
    )
    print(
        "Imported source catalog: "
        f"total={result.total} normalized={result.normalized} "
        f"inserted={result.inserted} updated={result.updated} skipped={result.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
