from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_OVERLAY = ROOT / "deploy" / "production" / "compose.release.ws7-production-20260723-r1.yaml"
ROLLBACK_OVERLAY = ROOT / "deploy" / "production" / "compose.rollback.pre-ws7-production-20260723-r1.yaml"
RUNBOOK = ROOT / "docs" / "production-release-runbook.md"


def test_current_release_overlay_pins_both_ws7_images_and_exact_rollback() -> None:
    release = RELEASE_OVERLAY.read_text(encoding="utf-8")
    rollback = ROLLBACK_OVERLAY.read_text(encoding="utf-8")

    assert "novel-pipeline-api:ws7-production-20260723-r1" in release
    assert "novel-pipeline-import-worker:ws7-production-20260723-r1" in release
    assert "novel-pipeline-api:ws6-production-20260723-r1" in rollback
    assert "novel-pipeline-import-worker:ws6-production-20260723-r1" in rollback


def test_production_runbook_declares_one_canonical_compose_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "PROJECT_NAME=novel-tnn-wsl" in runbook
    assert 'PRODUCTION_ENV="${HOME}/.config/novel-tnn/production.env"' in runbook
    assert "compose.release.ws7-production-20260723-r1.yaml" in runbook
    assert "compose.rollback.pre-ws7-production-20260723-r1.yaml" in runbook
    assert "docker compose -p \"$PROJECT_NAME\"" in runbook
    assert "config --images" in runbook
    assert "--no-build --force-recreate" in runbook
