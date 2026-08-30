from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "scripts" / "certify_glossary_phase6_browser.sh"


def test_browser_certification_orchestrator_declares_fresh_dual_viewport_journeys() -> None:
    result = subprocess.run(
        ["bash", str(ORCHESTRATOR), "--describe"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "cleanup": "automatic",
        "fixture_rows": 10_000,
        "journey": "full_each_viewport",
        "viewports": [
            {"height": 900, "name": "desktop", "width": 1440},
            {"height": 844, "name": "mobile", "width": 390},
        ],
    }
