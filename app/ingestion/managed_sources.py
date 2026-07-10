from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database.db import (
    get_managed_source,
    get_source_catalog_entry,
    import_managed_sources_from_catalog,
    record_managed_source_test,
    update_managed_source,
)
from app.ingestion.source_adapters import SourceAdapterError, validate_public_http_url
from app.ingestion.source_health import check_managed_source
from app.ingestion.source_policies import get_source_policy

SOURCE_STATUSES = {"IMPORTED", "NEEDS_REVIEW", "VERIFIED", "BROKEN", "BLOCKED"}
SOURCE_TRUST_LEVELS = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "MANUAL_ONLY"}
PARSER_TYPES = {"policy_supported", "generic_html"}


@dataclass(frozen=True)
class ManagedSourceImportSummary:
    selected: int
    inserted: int
    duplicates: int
    invalid: int
    skipped: int
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "skipped": self.skipped,
            "items": self.items,
        }


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_status(value: object, *, default: str = "NEEDS_REVIEW") -> str:
    normalized = _clean_text(value).upper() or default
    if normalized not in SOURCE_STATUSES:
        raise SourceAdapterError("Invalid source status")
    return normalized


def _normalize_trust(value: object, *, default: str = "MANUAL_ONLY") -> str:
    normalized = _clean_text(value).upper() or default
    if normalized not in SOURCE_TRUST_LEVELS:
        raise SourceAdapterError("Invalid source trust level")
    return normalized


def _safe_positive_int(value: object, *, minimum: int, maximum: int, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceAdapterError(f"Invalid {field_name}") from exc
    if parsed < minimum or parsed > maximum:
        raise SourceAdapterError(f"Invalid {field_name}")
    return parsed


def validate_parser_config(parser_type: str, parser_config: object) -> dict[str, Any]:
    normalized_parser_type = _clean_text(parser_type) or "policy_supported"
    if normalized_parser_type not in PARSER_TYPES:
        raise SourceAdapterError("Unsupported parser type")
    if parser_config in (None, ""):
        return {}
    if not isinstance(parser_config, dict):
        raise SourceAdapterError("Parser config must be a JSON object")

    allowed_keys = {"sample_url"} if normalized_parser_type == "generic_html" else set()
    unexpected = sorted(set(parser_config) - allowed_keys)
    if unexpected:
        raise SourceAdapterError("Parser config contains unsupported fields")

    safe_config: dict[str, Any] = {}
    sample_url = parser_config.get("sample_url")
    if "sample_url" in allowed_keys and sample_url:
        safe_config["sample_url"] = validate_public_http_url(str(sample_url))
    return safe_config


def build_managed_source_from_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    source_url = validate_public_http_url(str(entry.get("url") or ""))
    policy = get_source_policy(source_url)
    delay_seconds = policy.delay_seconds if policy else 12
    rpm = max(1, min(60, 60 // max(1, delay_seconds)))
    status = "NEEDS_REVIEW" if policy else "IMPORTED"
    return {
        "catalog_entry_id": str(entry.get("id") or ""),
        "name": _clean_text(entry.get("name") or entry.get("domain") or entry.get("url")),
        "base_url": source_url,
        "domain": str(entry.get("domain") or "").strip().casefold(),
        "language": "zh-CN",
        "parser_type": "policy_supported" if policy else "generic_html",
        "parser_config": {},
        "status": status,
        "trust_level": "MANUAL_ONLY",
        "supported_source_id": str(entry.get("supported_source_id") or (policy.source_id if policy else "")),
        "rate_limit_requests_per_minute": rpm,
        "rate_limit_delay_ms": delay_seconds * 1000,
        "max_concurrent_requests": policy.max_concurrency if policy else 1,
        "cooldown_after_error_seconds": max(delay_seconds * 30, 300),
        "notes": "",
    }


def import_selected_catalog_sources(db_path: Path, entry_ids: list[str]) -> ManagedSourceImportSummary:
    selected = [str(entry_id or "").strip() for entry_id in entry_ids if str(entry_id or "").strip()]
    if not selected:
        raise SourceAdapterError("Select at least one catalog source to import")

    prepared: list[dict[str, Any]] = []
    invalid = 0
    for entry_id in selected:
        entry = get_source_catalog_entry(db_path, entry_id)
        if entry is None:
            invalid += 1
            continue
        try:
            prepared.append(build_managed_source_from_catalog_entry(entry))
        except SourceAdapterError:
            invalid += 1

    summary = import_managed_sources_from_catalog(db_path, prepared)
    return ManagedSourceImportSummary(
        selected=len(selected),
        inserted=int(summary.get("inserted") or 0),
        duplicates=int(summary.get("duplicates") or 0),
        invalid=invalid + int(summary.get("invalid") or 0),
        skipped=int(summary.get("skipped") or 0),
        items=list(summary.get("items") or []),
    )


def validate_managed_source_update(payload: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if "status" in payload and payload["status"] is not None:
        updates["status"] = _normalize_status(payload["status"])
    if "trust_level" in payload and payload["trust_level"] is not None:
        updates["trust_level"] = _normalize_trust(payload["trust_level"])
    if "parser_type" in payload or "parser_config" in payload:
        parser_type = _clean_text(payload.get("parser_type")) or "policy_supported"
        parser_config = validate_parser_config(parser_type, payload.get("parser_config"))
        updates["parser_type"] = parser_type
        updates["parser_config"] = parser_config
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = str(payload["notes"])[:1000]
    if "rate_limit_requests_per_minute" in payload and payload["rate_limit_requests_per_minute"] is not None:
        updates["rate_limit_requests_per_minute"] = _safe_positive_int(
            payload["rate_limit_requests_per_minute"],
            minimum=1,
            maximum=120,
            field_name="rate_limit_requests_per_minute",
        )
    if "rate_limit_delay_ms" in payload and payload["rate_limit_delay_ms"] is not None:
        updates["rate_limit_delay_ms"] = _safe_positive_int(
            payload["rate_limit_delay_ms"],
            minimum=250,
            maximum=120000,
            field_name="rate_limit_delay_ms",
        )
    if "max_concurrent_requests" in payload and payload["max_concurrent_requests"] is not None:
        updates["max_concurrent_requests"] = _safe_positive_int(
            payload["max_concurrent_requests"],
            minimum=1,
            maximum=5,
            field_name="max_concurrent_requests",
        )
    if "cooldown_after_error_seconds" in payload and payload["cooldown_after_error_seconds"] is not None:
        updates["cooldown_after_error_seconds"] = _safe_positive_int(
            payload["cooldown_after_error_seconds"],
            minimum=30,
            maximum=86400,
            field_name="cooldown_after_error_seconds",
        )
    return updates


def test_existing_managed_source(db_path: Path, source_id: str) -> dict[str, Any]:
    source = get_managed_source(db_path, source_id)
    if source is None:
        raise SourceAdapterError("Managed source not found")
    if str(source.get("status") or "").upper() == "BLOCKED":
        raise SourceAdapterError("Blocked sources cannot be tested")

    result = check_managed_source(source)
    payload = result.to_dict()
    record_managed_source_test(db_path, payload)
    return payload


def verify_managed_source(db_path: Path, source_id: str) -> dict[str, Any]:
    source = get_managed_source(db_path, source_id)
    if source is None:
        raise SourceAdapterError("Managed source not found")
    if str(source.get("status") or "").upper() == "BLOCKED":
        raise SourceAdapterError("Blocked sources cannot be verified")
    if str(source.get("last_test_status") or "").lower() != "success":
        raise SourceAdapterError("Source must pass a safe fetch test before verification")
    updated = update_managed_source(db_path, source_id, status="VERIFIED", trust_level="HIGH")
    if updated is None:
        raise SourceAdapterError("Managed source not found")
    return updated
