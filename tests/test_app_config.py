from __future__ import annotations

from pathlib import Path

from app.config import Settings


def test_blank_legacy_artifact_root_remains_unset() -> None:
    assert Settings(artifact_legacy_root="").artifact_legacy_root is None


def test_configured_legacy_artifact_root_is_preserved() -> None:
    configured = Settings(artifact_legacy_root="/legacy/novel-tnn")

    assert configured.artifact_legacy_root == Path("/legacy/novel-tnn")
