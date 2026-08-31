from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = ROOT / "deploy" / "production"
CURRENT_RELEASE = PRODUCTION_DIR / "current-release.env"
OPERATIONAL_OBSERVABILITY_OVERLAY = (
    PRODUCTION_DIR / "compose.release.operational-observability-20260809-r1.yaml"
)
RUNBOOK = ROOT / "docs" / "production-release-runbook.md"
OPERATIONS_RUNBOOK = ROOT / "docs" / "operations" / "runtime-alerts-and-rollback.md"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _service_block(overlay: str, service: str) -> str:
    service_block = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        overlay,
    )
    assert service_block is not None
    return service_block.group("body")


def _service_image(overlay: str, service: str) -> str:
    image = re.search(
        r"^    image:\s*(?P<image>\S+)\s*$",
        _service_block(overlay, service),
        re.MULTILINE,
    )
    assert image is not None
    return image.group("image")


def _service_image_digest(overlay: str, service: str) -> str:
    digest = re.search(
        r'^      NOVEL_IMAGE_DIGEST:\s*["\']?(?P<digest>[^"\'\s]+)["\']?\s*$',
        _service_block(overlay, service),
        re.MULTILINE,
    )
    assert digest is not None
    return digest.group("digest")


def _current_release_contract() -> tuple[Path, Path, str]:
    lines = [
        line
        for line in CURRENT_RELEASE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assignments = dict(line.split("=", 1) for line in lines)

    assert len(lines) == 3
    assert set(assignments) == {
        "RELEASE_OVERLAY",
        "ROLLBACK_OVERLAY",
        "ROLLBACK_IMAGE_TAG",
    }

    release = ROOT / assignments["RELEASE_OVERLAY"]
    rollback = ROOT / assignments["ROLLBACK_OVERLAY"]
    assert release.parent == PRODUCTION_DIR
    assert rollback.parent == PRODUCTION_DIR
    assert release.is_file()
    assert rollback.is_file()
    assert assignments["ROLLBACK_IMAGE_TAG"]
    return release, rollback, assignments["ROLLBACK_IMAGE_TAG"]


def _release_version(overlay: Path) -> tuple[str, int]:
    match = re.search(
        r"-(?P<date>\d{8})-r(?P<revision>\d+)\.yaml$", overlay.name
    )
    assert match is not None
    return match.group("date"), int(match.group("revision"))


def test_current_release_pointer_selects_latest_release_pair() -> None:
    release_overlay, rollback_overlay, _ = _current_release_contract()
    release_overlays = list(PRODUCTION_DIR.glob("compose.release.*.yaml"))
    latest_release_version = max(map(_release_version, release_overlays))
    latest_release_overlays = [
        path
        for path in release_overlays
        if _release_version(path) == latest_release_version
    ]

    assert latest_release_overlays == [release_overlay]
    assert _release_version(rollback_overlay) == latest_release_version


def test_current_release_overlay_pins_both_images_and_exact_rollback() -> None:
    release_overlay, rollback_overlay, rollback_image_tag = (
        _current_release_contract()
    )
    release = release_overlay.read_text(encoding="utf-8")
    rollback = rollback_overlay.read_text(encoding="utf-8")
    release_id = release_overlay.name.removeprefix("compose.release.").removesuffix(".yaml")
    api_digest = _service_image_digest(release, "api")
    worker_digest = _service_image_digest(release, "import-worker")

    assert rollback_overlay.name == f"compose.rollback.pre-{release_id}.yaml"
    assert _service_image(release, "api") == f"novel-pipeline-api:{release_id}"
    assert _service_image(release, "import-worker") == f"novel-pipeline-import-worker:{release_id}"
    assert _service_image(rollback, "api") == f"novel-pipeline-api:{rollback_image_tag}"
    assert _service_image(rollback, "import-worker") == (
        f"novel-pipeline-import-worker:{rollback_image_tag}"
    )
    assert rollback_image_tag != release_id
    assert DIGEST_PATTERN.fullmatch(api_digest)
    assert DIGEST_PATTERN.fullmatch(worker_digest)
    assert api_digest != worker_digest


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
    assert "set -euo pipefail" in runbook
    assert "CURRENT_RELEASE=deploy/production/current-release.env" in runbook
    assert "unset RELEASE_OVERLAY ROLLBACK_OVERLAY ROLLBACK_IMAGE_TAG" in runbook
    assert 'source "$CURRENT_RELEASE"' in runbook
    for variable in ("RELEASE_OVERLAY", "ROLLBACK_OVERLAY", "ROLLBACK_IMAGE_TAG"):
        assert f': "${{{variable}:?}}"' in runbook
    assert re.search(
        r"(?m)^(?:RELEASE|ROLLBACK)_OVERLAY=deploy/production/compose\.", runbook
    ) is None
    assert "docker compose -p \"$PROJECT_NAME\"" in runbook
    assert "config --images" in runbook
    assert "--no-build --force-recreate" in runbook


def test_runtime_operations_runbook_uses_secret_safe_compose_render() -> None:
    runbook = OPERATIONS_RUNBOOK.read_text(encoding="utf-8")

    assert "PROJECT_NAME=novel-tnn-wsl" in runbook
    assert 'PRODUCTION_ENV="${HOME}/.config/novel-tnn/production.env"' in runbook
    assert 'docker compose -p "$PROJECT_NAME"' in runbook
    assert '--env-file "$PRODUCTION_ENV"' in runbook
    assert "config --quiet" in runbook
    assert "config --images" in runbook
    assert re.search(r"(?m)^\s+config\s*$", runbook) is None
