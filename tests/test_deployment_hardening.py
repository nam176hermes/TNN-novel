from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_firewall_runbook_blocks_private_network_for_browser_container() -> None:
    runbook = (ROOT / "docs/upgrade/P15_DEPLOYMENT_HARDENING.md").read_text(encoding="utf-8")

    assert "169.254.0.0/16" in runbook
    assert "127.0.0.0/8" in runbook
    assert "only HTTP/HTTPS and DNS" in runbook
