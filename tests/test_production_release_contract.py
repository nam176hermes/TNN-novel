from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RELEASE_OVERLAY = ROOT / "deploy" / "production" / "compose.release.ux-pwa-001-production-20260724-r1.yaml"
ROLLBACK_OVERLAY = ROOT / "deploy" / "production" / "compose.rollback.pre-ux-pwa-001-production-20260724-r1.yaml"
OPERATIONAL_OBSERVABILITY_OVERLAY = (
    ROOT
    / "deploy"
    / "production"
    / "compose.release.operational-observability-20260809-r1.yaml"
)
RUNBOOK = ROOT / "docs" / "production-release-runbook.md"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _service_image_digest(overlay: str, service: str) -> str:
    service_block = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        overlay,
    )
    assert service_block is not None
    digest = re.search(
        r'^      NOVEL_IMAGE_DIGEST:\s*["\']?(?P<digest>[^"\'\s]+)["\']?\s*$',
        service_block.group("body"),
        re.MULTILINE,
    )
    assert digest is not None
    return digest.group("digest")


def test_current_release_overlay_pins_both_images_and_exact_rollback() -> None:
    release = RELEASE_OVERLAY.read_text(encoding="utf-8")
    rollback = ROLLBACK_OVERLAY.read_text(encoding="utf-8")

    assert "novel-pipeline-api:ux-pwa-001-production-20260724-r1" in release
    assert "novel-pipeline-import-worker:ux-pwa-001-production-20260724-r1" in release
    assert "novel-pipeline-api:ws7-production-20260723-r1" in rollback
    assert "novel-pipeline-import-worker:ws7-production-20260723-r1" in rollback


def test_operational_observability_overlay_pins_distinct_immutable_image_ids() -> None:
    overlay = OPERATIONAL_OBSERVABILITY_OVERLAY.read_text(encoding="utf-8")
    api_digest = _service_image_digest(overlay, "api")
    worker_digest = _service_image_digest(overlay, "import-worker")

    assert DIGEST_PATTERN.fullmatch(api_digest)
    assert DIGEST_PATTERN.fullmatch(worker_digest)
    assert api_digest != worker_digest
    assert "unknown" not in overlay.lower()


def test_production_runbook_declares_one_canonical_compose_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "PROJECT_NAME=novel-tnn-wsl" in runbook
    assert 'PRODUCTION_ENV="${HOME}/.config/novel-tnn/production.env"' in runbook
    assert "compose.release.ux-pwa-001-production-20260724-r1.yaml" in runbook
    assert "compose.rollback.pre-ux-pwa-001-production-20260724-r1.yaml" in runbook
    assert "docker compose -p \"$PROJECT_NAME\"" in runbook
    assert "config --images" in runbook
    assert "--no-build --force-recreate" in runbook
