from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from app.ingestion.source_policies import get_source_policy

HEALTH_TIMEOUT_SECONDS = 5
HEALTH_MAX_READ_BYTES = 64 * 1024
HEALTH_USER_AGENT = "Novel-TNN SourceHealth/1.0"

RequestGet = Callable[..., requests.Response]


@dataclass(frozen=True)
class SourceHealthResult:
    catalog_entry_id: str
    domain: str
    status: str
    reason: str
    checked_at: str
    final_url: str = ""
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ManagedSourceTestResult:
    source_id: str
    domain: str
    status: str
    reason: str
    tested_at: str
    final_url: str = ""
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blocked_result(entry: dict[str, Any], reason: str) -> SourceHealthResult:
    return SourceHealthResult(
        catalog_entry_id=str(entry.get("id") or ""),
        domain=str(entry.get("domain") or ""),
        status="blocked",
        reason=reason,
        checked_at=_utcnow_text(),
    )


def _unsafe_ip_reason(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return ""
    if not ip.is_global:
        return "private_network_not_allowed"
    return ""


def _resolve_public_ips(hostname: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "dns_resolution_failed"
    except OSError:
        return "dns_resolution_failed"

    if not infos:
        return "dns_resolution_failed"
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            return "dns_resolution_failed"
        ip_text = str(sockaddr[0])
        reason = _unsafe_ip_reason(ip_text)
        if reason:
            return reason
    return ""


def validate_source_health_url(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return "", "unsupported_url_scheme"
    if not parsed.hostname:
        return "", "missing_hostname"
    if parsed.username or parsed.password:
        return "", "url_credentials_not_allowed"

    host = parsed.hostname.casefold().strip("[]").rstrip(".")
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost"):
        return "", "private_network_not_allowed"
    ip_reason = _unsafe_ip_reason(host)
    if ip_reason:
        return "", ip_reason

    dns_reason = _resolve_public_ips(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    if dns_reason:
        return "", dns_reason
    return parsed.geturl(), ""


def _read_limited_body(response: requests.Response) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        remaining = HEALTH_MAX_READ_BYTES - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= HEALTH_MAX_READ_BYTES:
            break
    return b"".join(chunks).decode("utf-8", errors="ignore")


def _safe_final_url(url: str) -> str:
    safe_url, reason = validate_source_health_url(url)
    return safe_url if not reason else ""


def sanitize_source_test_error(message: str) -> str:
    text = " ".join(str(message or "").replace("\n", " ").split())
    text = text.replace("\\", "/")
    text = text[:220]
    return text or "unknown_error"


def check_source_health(
    entry: dict[str, Any],
    *,
    request_get: RequestGet = requests.get,
) -> SourceHealthResult:
    url = str(entry.get("url") or "")
    safe_url, blocked_reason = validate_source_health_url(url)
    if blocked_reason:
        return _blocked_result(entry, blocked_reason)

    policy = get_source_policy(safe_url)
    if policy is None:
        return SourceHealthResult(
            catalog_entry_id=str(entry.get("id") or ""),
            domain=str(entry.get("domain") or urlparse(safe_url).hostname or ""),
            status="unsupported",
            reason="unsupported_source_policy",
            checked_at=_utcnow_text(),
        )

    headers = {
        "User-Agent": HEALTH_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
    }
    try:
        response = request_get(
            safe_url,
            headers=headers,
            timeout=HEALTH_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout:
        return SourceHealthResult(
            catalog_entry_id=str(entry.get("id") or ""),
            domain=str(entry.get("domain") or urlparse(safe_url).hostname or ""),
            status="timeout",
            reason="request_timeout",
            checked_at=_utcnow_text(),
        )
    except requests.RequestException:
        return SourceHealthResult(
            catalog_entry_id=str(entry.get("id") or ""),
            domain=str(entry.get("domain") or urlparse(safe_url).hostname or ""),
            status="error",
            reason="request_failed",
            checked_at=_utcnow_text(),
        )

    body = _read_limited_body(response)
    if policy.detects_cooldown(body):
        status = "captcha"
        reason = "captcha_or_cooldown_detected"
    elif int(response.status_code) >= 500:
        status = "error"
        reason = "server_error"
    else:
        status = "reachable"
        reason = "ok"

    return SourceHealthResult(
        catalog_entry_id=str(entry.get("id") or ""),
        domain=str(entry.get("domain") or urlparse(safe_url).hostname or ""),
        status=status,
        reason=reason,
        checked_at=_utcnow_text(),
        final_url=_safe_final_url(str(getattr(response, "url", safe_url) or safe_url)),
        http_status=int(response.status_code),
    )


def check_managed_source(
    source: dict[str, Any],
    *,
    request_get: RequestGet = requests.get,
) -> ManagedSourceTestResult:
    source_id = str(source.get("id") or "")
    source_status = str(source.get("status") or "").strip().upper()
    parser_type = str(source.get("parser_type") or "").strip() or "policy_supported"
    base_url = str(source.get("base_url") or "")
    safe_url, blocked_reason = validate_source_health_url(base_url)
    now = _utcnow_text()
    if source_status == "BLOCKED":
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or ""),
            status="blocked_by_policy",
            reason="source_blocked",
            tested_at=now,
        )
    if blocked_reason:
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or ""),
            status="invalid_url" if blocked_reason != "request_timeout" else "timeout",
            reason=blocked_reason,
            tested_at=now,
        )
    if parser_type not in {"policy_supported", "generic_html"}:
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or urlparse(safe_url).hostname or ""),
            status="parser_config_missing",
            reason="unsupported_parser_type",
            tested_at=now,
        )

    supported_source_id = str(source.get("supported_source_id") or "")
    policy = get_source_policy(safe_url)
    if parser_type == "policy_supported" and (not supported_source_id or policy is None):
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or urlparse(safe_url).hostname or ""),
            status="parser_config_missing",
            reason="supported_policy_required",
            tested_at=now,
        )

    timeout_seconds = min(12, max(5, (int(source.get("rate_limit_delay_ms") or 0) // 1000) + 2))
    headers = {
        "User-Agent": HEALTH_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
    }
    try:
        response = request_get(
            safe_url,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout:
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or urlparse(safe_url).hostname or ""),
            status="timeout",
            reason="request_timeout",
            tested_at=now,
        )
    except requests.RequestException as exc:
        return ManagedSourceTestResult(
            source_id=source_id,
            domain=str(source.get("domain") or urlparse(safe_url).hostname or ""),
            status="fetch_failed",
            reason=sanitize_source_test_error(str(exc)),
            tested_at=now,
        )

    body = _read_limited_body(response)
    final_url = _safe_final_url(str(getattr(response, "url", safe_url) or safe_url))
    if policy and policy.detects_cooldown(body):
        status = "blocked_by_policy"
        reason = "captcha_or_cooldown_detected"
    elif int(response.status_code) >= 500:
        status = "fetch_failed"
        reason = "server_error"
    elif not body.strip():
        status = "parse_failed"
        reason = "empty_response_body"
    else:
        status = "success"
        reason = "ok"

    return ManagedSourceTestResult(
        source_id=source_id,
        domain=str(source.get("domain") or urlparse(safe_url).hostname or ""),
        status=status,
        reason=reason,
        tested_at=now,
        final_url=final_url,
        http_status=int(response.status_code),
    )
