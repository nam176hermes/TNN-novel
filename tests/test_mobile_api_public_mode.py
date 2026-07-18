from __future__ import annotations

from starlette.requests import Request

from app.mobile_api import public_mode


def _request(*, client_host: str, host_header: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/ready",
            "query_string": b"",
            "headers": [(b"host", host_header.encode("ascii"))],
            "client": (client_host, 43120),
            "server": ("127.0.0.1", 7860),
        }
    )


def test_public_mode_does_not_trust_forged_localhost_header(monkeypatch) -> None:
    monkeypatch.setattr(public_mode.mobile_settings, "public_deploy", False)

    assert public_mode.is_public_request(_request(client_host="198.51.100.10", host_header="localhost")) is True


def test_public_mode_keeps_actual_loopback_peer_local(monkeypatch) -> None:
    monkeypatch.setattr(public_mode.mobile_settings, "public_deploy", False)

    assert public_mode.is_public_request(_request(client_host="127.0.0.1", host_header="localhost")) is False
