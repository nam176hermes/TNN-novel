from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import ipaddress

from app.database.db import upsert_source_catalog_entries
from app.ingestion.source_policies import get_source_policy


TAG_MAP = {
    "搜": "search",
    "发": "explore",
    "图": "manga",
    "声": "audio",
}
SUPPORTED_CATALOG_SOURCES = {"yckceo", "novela"}


@dataclass(frozen=True)
class SourceCatalogImportResult:
    total: int
    normalized: int
    inserted: int
    updated: int
    skipped: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "normalized": self.normalized,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _catalog_source_name(catalog_source: str) -> str:
    normalized = _clean_text(catalog_source).casefold() or "yckceo"
    return normalized if normalized in SUPPORTED_CATALOG_SOURCES else "yckceo"


def _stable_catalog_id(*, catalog_source: str, external_id: str, url: str, name: str) -> tuple[str, str]:
    clean_external_id = _clean_text(external_id)
    if clean_external_id:
        return f"{catalog_source}:{clean_external_id}", clean_external_id
    digest = hashlib.sha256(f"{catalog_source}|{url}|{name}".encode("utf-8")).hexdigest()[:24]
    return f"{catalog_source}:generated:{digest}", f"generated:{digest}"


def normalize_catalog_tags(raw_tags: object) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    normalized: list[str] = []
    unknown: list[str] = []
    for token in re.split(r"[\s,;，、|]+", _clean_text(raw_tags)):
        clean = token.strip()
        if not clean:
            continue
        mapped = TAG_MAP.get(clean)
        if mapped:
            if mapped not in seen:
                normalized.append(mapped)
                seen.add(mapped)
        elif len(clean) <= 32 and not any(ord(char) < 32 for char in clean):
            unknown.append(clean)
    return normalized, unknown


def normalize_catalog_url(raw_url: object) -> tuple[str, str, str]:
    url = _clean_text(raw_url)
    if not url:
        return "", "", "missing_url"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url, "", "unsupported_url_scheme"
    if not parsed.hostname:
        return url, "", "missing_hostname"
    if parsed.username or parsed.password:
        return url, "", "url_credentials_not_allowed"

    host = parsed.hostname.casefold().strip("[]").rstrip(".")
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost"):
        return url, host, "local_hostname_not_allowed"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return parsed.geturl(), host, ""
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return parsed.geturl(), host, "private_network_not_allowed"
    return parsed.geturl(), host, ""


def normalize_source_catalog_entry(
    raw: Mapping[str, Any],
    *,
    catalog_source: str = "yckceo",
) -> dict[str, Any]:
    source = _catalog_source_name(catalog_source)
    name = _clean_text(raw.get("name"))
    url, domain, invalid_reason = normalize_catalog_url(raw.get("url"))
    external_id = _clean_text(raw.get("id") or raw.get("external_id"))
    entry_id, external_id = _stable_catalog_id(
        catalog_source=source,
        external_id=external_id,
        url=url,
        name=name,
    )
    tags, unknown_tags = normalize_catalog_tags(raw.get("tags"))
    policy = get_source_policy(url) if not invalid_reason else None
    supported_status = "supported" if policy else ("invalid_url" if invalid_reason else "unsupported")
    return {
        "id": entry_id,
        "external_id": external_id,
        "catalog_source": source,
        "name": name,
        "url": url,
        "domain": domain,
        "author": _clean_text(raw.get("author")),
        "downloads": _safe_int(raw.get("downloads")),
        "version": _clean_text(raw.get("version")),
        "raw_tags": _clean_text(raw.get("tags")),
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "unknown_tags_json": json.dumps(unknown_tags, ensure_ascii=False),
        "supported_status": supported_status,
        "supported_source_id": policy.source_id if policy else "",
        "invalid_reason": invalid_reason,
        "updated_label": _clean_text(raw.get("time") or raw.get("updated_label")),
    }


def normalize_source_catalog_entries(
    rows: Iterable[Mapping[str, Any]],
    *,
    catalog_source: str = "yckceo",
) -> list[dict[str, Any]]:
    return [
        normalize_source_catalog_entry(row, catalog_source=catalog_source)
        for row in rows
    ]


def load_source_catalog_json(path: Path) -> list[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("Source catalog JSON must be a list of objects")
    rows: list[Mapping[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        rows.append(item)
    return rows


def import_source_catalog_json(
    db_path: Path,
    catalog_path: Path,
    *,
    catalog_source: str = "yckceo",
) -> SourceCatalogImportResult:
    rows = load_source_catalog_json(catalog_path)
    entries = normalize_source_catalog_entries(rows, catalog_source=catalog_source)
    summary = upsert_source_catalog_entries(db_path, entries)
    return SourceCatalogImportResult(
        total=len(rows),
        normalized=len(entries),
        inserted=summary["inserted"],
        updated=summary["updated"],
        skipped=summary["skipped"],
    )
