from __future__ import annotations

import pytest


def _resolver(mapping: dict[str, list[str]]):
    def resolve(hostname: str, port: int) -> list[str]:
        return mapping.get(hostname, ["93.184.216.34"])

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/book",
        "http://127.0.0.1/book",
        "http://[::1]/book",
        "http://10.0.0.1/book",
        "http://169.254.1.1/book",
        "http://224.0.0.1/book",
        "http://240.0.0.1/book",
        "http://metadata/book",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_url_policy_blocks_local_private_linklocal_multicast_reserved_and_metadata(url: str) -> None:
    from app.security.url_policy import UrlPolicyViolation, validate_fetch_url

    with pytest.raises(UrlPolicyViolation):
        validate_fetch_url(url, resolver=_resolver({"metadata": ["93.184.216.34"]}))


def test_url_policy_allows_fake_public_ip_and_canonicalizes_idna_hostname() -> None:
    from app.security.url_policy import validate_fetch_url

    result = validate_fetch_url(
        "https://bücher.example/path?q=1#fragment",
        resolver=_resolver({"xn--bcher-kva.example": ["93.184.216.34"]}),
    )

    assert result.hostname == "xn--bcher-kva.example"
    assert result.port == 443
    assert result.canonical_url == "https://xn--bcher-kva.example/path?q=1"
    assert result.ip_addresses == ("93.184.216.34",)


@pytest.mark.parametrize("url", ["https://user:pass@www.69shuba.com/book/1", "https://www.69shuba.com:444/book/1"])
def test_url_policy_blocks_credentials_and_unapproved_ports(url: str) -> None:
    from app.security.url_policy import UrlPolicyViolation, validate_fetch_url

    with pytest.raises(UrlPolicyViolation):
        validate_fetch_url(url, resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}))


def test_url_policy_blocks_dns_resolution_to_private_ip() -> None:
    from app.security.url_policy import UrlPolicyViolation, validate_fetch_url

    with pytest.raises(UrlPolicyViolation) as exc:
        validate_fetch_url(
            "https://www.69shuba.com/book/1",
            resolver=_resolver({"www.69shuba.com": ["10.0.0.10"]}),
        )

    assert exc.value.code == "private_network_blocked"


def test_url_policy_blocks_url_outside_adapter_domains() -> None:
    from app.security.url_policy import UrlPolicyViolation, validate_fetch_url

    with pytest.raises(UrlPolicyViolation) as exc:
        validate_fetch_url(
            "https://www.biquge.tw/book/1",
            resolver=_resolver({"www.biquge.tw": ["93.184.216.34"]}),
            allowed_domains=("69shuba.com", "69shuba.cx"),
        )

    assert exc.value.code == "source_not_allowed"


@pytest.mark.parametrize(
    "query_name",
    (
        "apiKeyboard",
        "tokenizer",
        "token_budget",
        "cookie_policy",
        "passwordless",
        "secretary",
    ),
)
def test_url_policy_preserves_ordinary_query_names_that_contain_sensitive_fragments(
    query_name: str,
) -> None:
    from app.security.url_policy import validate_fetch_url

    url = f"https://www.69shuba.com/book/1?{query_name}=public-setting"

    result = validate_fetch_url(
        url,
        resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}),
    )

    assert result.canonical_url == url


@pytest.mark.parametrize(
    "query_name",
    (
        "apiKey",
        "API%2EKEY",
        "openaiApiKey",
        "openaiapikey",
        "remote_api_key",
        "remoteapikey",
        "access_token",
        "refresh-token",
        "authorization",
        "admin_password",
        "client_secret",
        "cookie",
        "session_cookie",
        "usercredential",
        "providercredential",
        "apitoken",
        "secretkey",
        "authcookie",
    ),
)
def test_url_policy_rejects_precise_credential_query_names(query_name: str) -> None:
    from app.security.url_policy import UrlPolicyViolation, validate_fetch_url

    with pytest.raises(UrlPolicyViolation, match="credential query"):
        validate_fetch_url(
            f"https://www.69shuba.com/book/1?{query_name}=canary",
            resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}),
        )


@pytest.mark.parametrize(
    "query_name",
    (
        "usercredentialguide",
        "providercredentialing",
        "apitokenizer",
        "secretkeyboard",
        "authcookieless",
    ),
)
def test_url_policy_preserves_joined_credential_lookalikes(query_name: str) -> None:
    from app.security.url_policy import validate_fetch_url

    url = f"https://www.69shuba.com/book/1?{query_name}=public-setting"

    result = validate_fetch_url(
        url,
        resolver=_resolver({"www.69shuba.com": ["93.184.216.34"]}),
    )

    assert result.canonical_url == url
