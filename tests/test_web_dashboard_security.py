from __future__ import annotations

import pytest

from app.ui import web_dashboard


def test_legacy_dashboard_only_allows_loopback_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}
    monkeypatch.setattr(web_dashboard.uvicorn, "run", lambda app, host, port: called.update(host=host, port=port))

    web_dashboard.start_server(host="127.0.0.1", port=8000)

    assert called == {"host": "127.0.0.1", "port": 8000}


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "dashboard.example.com"])
def test_legacy_dashboard_rejects_non_loopback_bind(host: str) -> None:
    with pytest.raises(ValueError, match="local-only"):
        web_dashboard.start_server(host=host)
