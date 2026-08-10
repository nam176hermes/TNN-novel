from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import SplitResult, quote, unquote, urljoin, urlsplit, urlunsplit


UrlResolver = Callable[[str, int], Iterable[str]]

DEFAULT_ALLOWED_PORTS = frozenset({80, 443})
METADATA_HOSTNAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.azure.internal",
        "169.254.169.254",
        "100.100.100.200",
    }
)


@dataclass(frozen=True)
class UrlPolicyViolation(ValueError):
    message: str
    code: str = "invalid_url"

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


@dataclass(frozen=True)
class UrlPolicyResult:
    canonical_url: str
    hostname: str
    port: int
    ip_addresses: tuple[str, ...]


def default_resolver(hostname: str, port: int) -> tuple[str, ...]:
    addresses: list[str] = []
    for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    ):
        host = sockaddr[0]
        if host not in addresses:
            addresses.append(host)
    return tuple(addresses)


def redacted_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    hostname = _canonical_hostname(parsed)
    if not hostname:
        return "[invalid-url]"
    netloc = _netloc(hostname, _effective_port(parsed), parsed.scheme.lower())
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", "", ""))


def validate_fetch_url(
    url: str,
    *,
    resolver: UrlResolver | None = None,
    allowed_domains: Iterable[str] | None = None,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> UrlPolicyResult:
    parsed = _parse_url(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UrlPolicyViolation("Only http/https source URLs are supported", code="invalid_url")
    if parsed.username or parsed.password:
        raise UrlPolicyViolation("URL credentials are not allowed", code="invalid_url")
    hostname = _canonical_hostname(parsed)
    if not hostname:
        raise UrlPolicyViolation("URL must include a hostname", code="invalid_url")
    if hostname in METADATA_HOSTNAMES or hostname.endswith(".metadata"):
        raise UrlPolicyViolation("Metadata hostnames are not allowed", code="private_network_blocked")
    port = _effective_port(parsed)
    if port not in set(allowed_ports):
        raise UrlPolicyViolation("URL port is not allowed", code="invalid_url")
    ip_addresses = _literal_or_resolved_ips(hostname, port, resolver)
    for address in ip_addresses:
        _raise_if_blocked_ip(address)
    if allowed_domains and not _hostname_matches_any(hostname, allowed_domains):
        raise UrlPolicyViolation("URL is outside the allowed source domains", code="source_not_allowed")

    canonical = _canonical_url(parsed, hostname, port)
    return UrlPolicyResult(
        canonical_url=canonical,
        hostname=hostname,
        port=port,
        ip_addresses=tuple(ip_addresses),
    )


def resolve_redirect_url(
    current_url: str,
    location: str,
    *,
    resolver: UrlResolver | None = None,
    allowed_domains: Iterable[str] | None = None,
    allowed_ports: Iterable[int] = DEFAULT_ALLOWED_PORTS,
) -> UrlPolicyResult:
    return validate_fetch_url(
        urljoin(current_url, location),
        resolver=resolver,
        allowed_domains=allowed_domains,
        allowed_ports=allowed_ports,
    )


def _parse_url(url: str) -> SplitResult:
    try:
        return urlsplit(url.strip())
    except ValueError as exc:
        raise UrlPolicyViolation("Invalid URL", code="invalid_url") from exc


def _canonical_hostname(parsed: SplitResult) -> str:
    try:
        host = parsed.hostname or ""
    except ValueError as exc:
        raise UrlPolicyViolation("Invalid URL hostname", code="invalid_url") from exc
    host = host.strip("[]").rstrip(".").casefold()
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost"):
        raise UrlPolicyViolation("Localhost source URLs are not allowed", code="private_network_blocked")
    try:
        return host.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UrlPolicyViolation("Invalid URL hostname", code="invalid_url") from exc


def _effective_port(parsed: SplitResult) -> int:
    try:
        explicit = parsed.port
    except ValueError as exc:
        raise UrlPolicyViolation("Invalid URL port", code="invalid_url") from exc
    if explicit is not None:
        return explicit
    return 443 if parsed.scheme.lower() == "https" else 80


def _netloc(hostname: str, port: int, scheme: str) -> str:
    needs_brackets = ":" in hostname and not hostname.startswith("[")
    rendered_host = f"[{hostname}]" if needs_brackets else hostname
    default_port = 443 if scheme == "https" else 80
    return rendered_host if port == default_port else f"{rendered_host}:{port}"


def _canonical_url(parsed: SplitResult, hostname: str, port: int) -> str:
    scheme = parsed.scheme.lower()
    path = quote(unquote(parsed.path or "/"), safe="/:@!$&'()*+,;=-._~")
    query = parsed.query
    return urlunsplit((scheme, _netloc(hostname, port, scheme), path, query, ""))


def _hostname_matches_any(hostname: str, allowed_domains: Iterable[str]) -> bool:
    normalized_domains = tuple(
        domain.strip().rstrip(".").casefold().encode("idna").decode("ascii")
        for domain in allowed_domains
        if domain.strip()
    )
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in normalized_domains)


def _literal_or_resolved_ips(hostname: str, port: int, resolver: UrlResolver | None) -> tuple[str, ...]:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return (hostname,)
    if resolver is None:
        return ()
    try:
        return tuple(str(address) for address in resolver(hostname, port))
    except OSError as exc:
        raise UrlPolicyViolation("DNS resolution failed", code="source_unavailable") from exc


def _raise_if_blocked_ip(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UrlPolicyViolation("DNS returned an invalid IP address", code="source_unavailable") from exc
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or not ip.is_global
    ):
        raise UrlPolicyViolation("Private or reserved network targets are not allowed", code="private_network_blocked")
