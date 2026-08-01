from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


PROVIDER_ENV_NAME = "GEMINI_API_KEY"
OTHER_PROVIDER_ENV_NAME = "OPENAI_API_KEY"


def make_synthetic_key() -> str:
    return secrets.token_urlsafe(32)


def assert_secret_matches(actual: str, expected: str) -> None:
    if not hmac.compare_digest(actual, expected):
        pytest.fail("stored provider key did not match the generated value")


def assert_secret_absent(secret: str, *rendered_values: object) -> None:
    if any(secret in str(value) for value in rendered_values):
        pytest.fail("synthetic provider key was exposed")


def make_store(path: Path):
    from app.mobile_api.services.provider_secret_store import ProviderSecretStore

    return ProviderSecretStore(path)


def test_save_creates_versioned_store_with_private_modes(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    generated_key = make_synthetic_key()
    store = make_store(store_path)

    store.save(PROVIDER_ENV_NAME, generated_key)

    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert set(payload["keys"]) == {PROVIDER_ENV_NAME}
    assert payload["deleted"] == []
    assert_secret_matches(payload["keys"][PROVIDER_ENV_NAME], generated_key)
    assert stat.S_IMODE(store_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(store_path.stat().st_mode) == 0o600


def test_replace_removes_prior_value_and_leaves_no_temp_file(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    first_key = make_synthetic_key()
    second_key = make_synthetic_key()
    store = make_store(store_path)
    store.save(PROVIDER_ENV_NAME, first_key)

    store.save(PROVIDER_ENV_NAME, second_key)

    raw_store = store_path.read_text(encoding="utf-8")
    payload = json.loads(raw_store)
    assert_secret_matches(payload["keys"][PROVIDER_ENV_NAME], second_key)
    assert_secret_absent(first_key, raw_store)
    if list(store_path.parent.glob(".provider-keys.*.tmp")):
        pytest.fail("provider secret-store temporary file was left behind")


def test_delete_removes_only_requested_environment_key(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    first_key = make_synthetic_key()
    second_key = make_synthetic_key()
    store = make_store(store_path)
    store.save(PROVIDER_ENV_NAME, first_key)
    store.save(OTHER_PROVIDER_ENV_NAME, second_key)

    store.delete(PROVIDER_ENV_NAME)

    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert set(payload["keys"]) == {OTHER_PROVIDER_ENV_NAME}
    assert payload["deleted"] == [PROVIDER_ENV_NAME]
    assert_secret_matches(payload["keys"][OTHER_PROVIDER_ENV_NAME], second_key)
    assert_secret_absent(first_key, store_path.read_text(encoding="utf-8"))


def test_save_removes_existing_tombstone(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    generated_key = make_synthetic_key()
    store = make_store(store_path)
    store.delete(PROVIDER_ENV_NAME)

    store.save(PROVIDER_ENV_NAME, generated_key)

    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["deleted"] == []
    assert_secret_matches(payload["keys"][PROVIDER_ENV_NAME], generated_key)


def test_v1_store_is_read_compatibly_and_rewritten_on_mutation(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    generated_key = make_synthetic_key()
    store_path.write_text(
        json.dumps({"version": 1, "keys": {PROVIDER_ENV_NAME: generated_key}}),
        encoding="utf-8",
    )
    store_path.chmod(0o600)
    store = make_store(store_path)

    loaded = store.load()
    store.save(OTHER_PROVIDER_ENV_NAME, make_synthetic_key())

    assert_secret_matches(loaded[PROVIDER_ENV_NAME], generated_key)
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["deleted"] == []


def test_store_rejects_names_outside_product_allowlist(tmp_path: Path) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    generated_key = make_synthetic_key()
    store = make_store(tmp_path / "secrets" / "provider-keys.json")

    with pytest.raises(ProviderSecretStoreError) as exc_info:
        store.save("UNRELATED_SECRET", generated_key)

    assert str(exc_info.value) == "Provider secret value is invalid"
    assert_secret_absent(generated_key, exc_info.value)


def test_store_rejects_unallowlisted_v1_keys_without_installing_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    generated_key = make_synthetic_key()
    store_path.write_text(
        json.dumps({"version": 1, "keys": {"UNRELATED_SECRET": generated_key}}),
        encoding="utf-8",
    )
    store_path.chmod(0o600)
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)

    with pytest.raises(ProviderSecretStoreError):
        make_store(store_path).load_into_environment()

    assert "UNRELATED_SECRET" not in os.environ


def test_default_path_is_private_config_and_outside_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.provider_secret_store import provider_secret_store_path

    config_home = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.delenv("PROVIDER_SECRET_STORE_PATH", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    resolved = provider_secret_store_path()

    assert resolved == config_home / "novel-tnn" / "provider-keys.json"
    assert data_dir not in resolved.parents


def test_explicit_store_path_contract_takes_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.provider_secret_store import provider_secret_store_path

    expected = tmp_path / "api-only" / "provider-keys.json"
    monkeypatch.setenv("PROVIDER_SECRET_STORE_PATH", str(expected))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ignored"))

    assert provider_secret_store_path() == expected


def test_load_repairs_existing_regular_file_mode_before_use(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    generated_key = make_synthetic_key()
    store_path.write_text(
        json.dumps({"version": 1, "keys": {PROVIDER_ENV_NAME: generated_key}}),
        encoding="utf-8",
    )
    store_path.chmod(0o644)

    loaded = make_store(store_path).load()

    assert_secret_matches(loaded[PROVIDER_ENV_NAME], generated_key)
    assert stat.S_IMODE(store_path.stat().st_mode) == 0o600


def test_malformed_store_failure_is_sanitized(tmp_path: Path) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    generated_key = make_synthetic_key()
    store_path.write_text(
        json.dumps({"version": 2, "keys": {PROVIDER_ENV_NAME: generated_key}}),
        encoding="utf-8",
    )
    store_path.chmod(0o600)

    with pytest.raises(ProviderSecretStoreError) as exc_info:
        make_store(store_path).load()

    if str(exc_info.value) != "Provider secret store is malformed":
        pytest.fail("malformed provider secret-store error was not sanitized")
    assert_secret_absent(generated_key, exc_info.value)


def test_symlink_store_is_rejected_with_sanitized_failure(tmp_path: Path) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    target_path = tmp_path / "outside.json"
    generated_key = make_synthetic_key()
    target_path.write_text(
        json.dumps({"version": 1, "keys": {PROVIDER_ENV_NAME: generated_key}}),
        encoding="utf-8",
    )
    store_path = secrets_dir / "provider-keys.json"
    store_path.symlink_to(target_path)

    with pytest.raises(ProviderSecretStoreError) as exc_info:
        make_store(store_path).load()

    if str(exc_info.value) != "Provider secret store is unsafe":
        pytest.fail("unsafe provider secret-store error was not sanitized")
    assert_secret_absent(generated_key, exc_info.value)


def test_prepare_runtime_loads_persisted_keys_into_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    store_path = tmp_path / "config" / "provider-keys.json"
    monkeypatch.setenv("PROVIDER_SECRET_STORE_PATH", str(store_path))
    from app.mobile_api import main as main_mod

    monkeypatch.setattr(main_mod, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(main_mod, "get_db_path", lambda: data_dir / "pipeline.db")
    data_dir.mkdir()
    monkeypatch.delenv(PROVIDER_ENV_NAME, raising=False)
    generated_key = make_synthetic_key()
    make_store(store_path).save(PROVIDER_ENV_NAME, generated_key)

    main_mod._prepare_runtime()

    assert_secret_matches(os.environ[PROVIDER_ENV_NAME], generated_key)


def test_prepare_runtime_unsets_tombstoned_baseline_environment_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    store_path = tmp_path / "config" / "provider-keys.json"
    monkeypatch.setenv("PROVIDER_SECRET_STORE_PATH", str(store_path))
    from app.mobile_api import main as main_mod

    monkeypatch.setattr(main_mod, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(main_mod, "get_db_path", lambda: data_dir / "pipeline.db")
    data_dir.mkdir()
    monkeypatch.setenv(PROVIDER_ENV_NAME, make_synthetic_key())
    make_store(store_path).delete(PROVIDER_ENV_NAME)

    main_mod._prepare_runtime()

    assert PROVIDER_ENV_NAME not in os.environ


def test_directory_fsync_failure_after_commit_returns_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    generated_key = make_synthetic_key()
    store = make_store(store_path)
    real_fsync = os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    result = store.save(PROVIDER_ENV_NAME, generated_key)

    assert result.committed is True
    assert result.durable is False
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert_secret_matches(payload["keys"][PROVIDER_ENV_NAME], generated_key)


def test_default_path_home_resolution_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.provider_secret_store import (
        ProviderSecretStoreError,
        provider_secret_store_path,
    )

    private_marker = "synthetic-private-home-marker"
    monkeypatch.delenv("PROVIDER_SECRET_STORE_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError(private_marker))),
    )

    with pytest.raises(ProviderSecretStoreError) as exc_info:
        provider_secret_store_path()

    assert str(exc_info.value) == "Provider secret store path is unavailable"
    assert private_marker not in str(exc_info.value)


def test_precommit_temp_cleanup_failure_is_reported_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    store_path = tmp_path / "secrets" / "provider-keys.json"
    generated_key = make_synthetic_key()
    store = make_store(store_path)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        patcher.setattr(os, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        with pytest.raises(ProviderSecretStoreError) as exc_info:
            store.save(PROVIDER_ENV_NAME, generated_key)

    assert str(exc_info.value) == "Provider secret store cleanup failed"
    assert_secret_absent(generated_key, exc_info.value)


def test_existing_fifo_store_fails_closed_without_hanging(tmp_path: Path) -> None:
    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    os.mkfifo(store_path, mode=0o600)
    script = (
        "from pathlib import Path;"
        "from app.mobile_api.services.provider_secret_store import ProviderSecretStore,ProviderSecretStoreError;"
        "\ntry: ProviderSecretStore(Path(__import__('sys').argv[1])).load()"
        "\nexcept ProviderSecretStoreError: raise SystemExit(0)"
        "\nraise SystemExit(1)"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(store_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("provider secret-store FIFO open blocked")

    assert result.returncode == 0


def test_existing_fifo_lock_fails_closed_without_hanging(tmp_path: Path) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    os.mkfifo(store_path.with_name(f"{store_path.name}.lock"), mode=0o600)

    started = time.monotonic()
    with pytest.raises(ProviderSecretStoreError):
        make_store(store_path).save(PROVIDER_ENV_NAME, make_synthetic_key())

    assert time.monotonic() - started < 1


def test_symlink_lock_is_rejected(tmp_path: Path) -> None:
    from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    target = tmp_path / "outside.lock"
    target.touch(mode=0o600)
    store_path.with_name(f"{store_path.name}.lock").symlink_to(target)

    with pytest.raises(ProviderSecretStoreError):
        make_store(store_path).save(PROVIDER_ENV_NAME, make_synthetic_key())


def test_process_lock_serializes_full_mutation(tmp_path: Path) -> None:
    import fcntl

    store_path = tmp_path / "secrets" / "provider-keys.json"
    store_path.parent.mkdir(mode=0o700)
    lock_path = store_path.with_name(f"{store_path.name}.lock")
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    generated_key = make_synthetic_key()
    script = (
        "import sys;from pathlib import Path;"
        "from app.mobile_api.services.provider_secret_store import ProviderSecretStore;"
        "ProviderSecretStore(Path(sys.argv[1])).save('GEMINI_API_KEY',sys.stdin.read())"
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(store_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(generated_key.encode("utf-8"))
        process.stdin.close()
        process.stdin = None
        time.sleep(0.2)
        if process.poll() is not None:
            pytest.fail("provider mutation bypassed the process lock")
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=3)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()

    if process.returncode != 0:
        pytest.fail("provider mutation subprocess failed")
    assert_secret_absent(generated_key, stdout, stderr)
    assert_secret_matches(make_store(store_path).load()[PROVIDER_ENV_NAME], generated_key)
