from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    path = ROOT / "scripts" / "check-runtime-contract.py"
    spec = importlib.util.spec_from_file_location("check_runtime_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inspect(component: str) -> dict:
    limits = {
        "api": (768 * 1024 * 1024, 1_000_000_000, 256),
        "import-worker": (1536 * 1024 * 1024, 2_000_000_000, 384),
    }[component]
    return {
        "Name": f"/novel-tnn-wsl-{component}-1",
        "Config": {
            "User": "novel",
            "Labels": {"com.docker.compose.service": component},
            "Healthcheck": {"Test": ["CMD-SHELL", "true"]},
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": limits[2],
            "Memory": limits[0],
            "NanoCpus": limits[1],
            "RestartPolicy": {"Name": "unless-stopped"},
        },
    }


def test_runtime_contract_accepts_hardened_api_and_worker() -> None:
    checker = _load_checker()

    assert checker.validate_container(_inspect("api")) == []
    assert checker.validate_container(_inspect("import-worker")) == []


def test_runtime_contract_reproduces_unhardened_api_drift() -> None:
    checker = _load_checker()
    api = _inspect("api")
    api["HostConfig"].update(
        CapDrop=None,
        SecurityOpt=None,
        PidsLimit=0,
        Memory=0,
        NanoCpus=0,
    )

    errors = checker.validate_container(api)

    assert "all Linux capabilities must be dropped" in errors
    assert "no-new-privileges must be enabled" in errors
    assert any(error.startswith("PID limit") for error in errors)
    assert any(error.startswith("memory limit") for error in errors)
    assert any(error.startswith("CPU limit") for error in errors)


def test_canonical_compose_keeps_api_and_worker_runtime_controls() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    api = compose.split("  api:", 1)[1].split("  import-worker:", 1)[0]
    worker = compose.split("  import-worker:", 1)[1]

    for service in (api, worker):
        assert "read_only: true" in service
        assert "no-new-privileges:true" in service
        assert "cap_drop:\n      - ALL" in service
        assert "pids_limit:" in service
        assert "cpus:" in service
        assert "mem_limit:" in service
        assert "healthcheck:" in service
        assert "restart: unless-stopped" in service
