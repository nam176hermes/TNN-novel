from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_separates_api_and_import_browser_worker_without_api_secrets() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "  api:" in compose
    assert "  import-worker:" in compose
    api = compose.split("  api:", 1)[1].split("  import-worker:", 1)[0]
    worker = compose.split("  import-worker:", 1)[1]
    assert "target: import-worker" in worker
    assert "IMPORT_JOB_RUN_IN_API: \"0\"" in compose
    assert "MOBILE_API_SECRET" not in worker
    assert "MOBILE_API_ADMIN_PASSWORD" not in worker
    assert "ARTIFACT_LEGACY_ROOT" not in compose
    assert "EBOOK_INBOX_DIR: /data/inbox/ebooks" in api
    assert (
        'MOBILE_API_CORS_ORIGINS: "${MOBILE_API_CORS_ORIGINS:-http://localhost,http://127.0.0.1,https://novel-tnn.tradingcompanydirect.com}"'
        in api
    )
    assert "pids_limit:" in worker
    assert "tmpfs:" in worker
    assert "--healthcheck" in worker


def test_dockerfile_has_non_root_api_and_browser_worker_targets() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM runtime-base AS import-worker" in dockerfile
    assert "FROM runtime-base AS api" in dockerfile
    assert "playwright install --with-deps chromium" in dockerfile
    assert "USER novel" in dockerfile


def test_runtime_commands_set_private_file_umask_for_sqlite_sidecars() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'CMD ["sh", "-c", "umask 007 && exec python -m app.mobile_api"]' in dockerfile
    assert 'CMD ["sh", "-c", "umask 007 && exec python -m app.import_worker"]' in dockerfile
    assert 'command: ["sh", "-c", "umask 007 && exec python -m app.import_worker"]' in compose


def test_firewall_runbook_blocks_private_network_for_browser_container() -> None:
    runbook = (ROOT / "docs/upgrade/P15_DEPLOYMENT_HARDENING.md").read_text(encoding="utf-8")

    assert "169.254.0.0/16" in runbook
    assert "127.0.0.0/8" in runbook
    assert "only HTTP/HTTPS and DNS" in runbook
