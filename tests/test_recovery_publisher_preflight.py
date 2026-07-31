from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "verify_recovery_publisher.py"
PROBE_PATTERN = ".recovery-publisher-probe-*"


def _load_helper() -> ModuleType:
    assert HELPER.is_file(), "recovery publisher preflight helper is missing"
    spec = importlib.util.spec_from_file_location("verify_recovery_publisher", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_layout(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    receipt_dir = data_root / "logs" / "runtime"
    receipt_dir.mkdir(parents=True)
    receipt_dir.chmod(0o700)
    return data_root, receipt_dir


def _verify(
    module: ModuleType,
    data_root: Path,
    receipt_dir: Path,
    *,
    expected_release: str = "release-a",
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    expected_data_root_identity: str | None = None,
) -> None:
    data_metadata = data_root.stat()
    module.verify_recovery_publisher(
        data_root,
        receipt_dir,
        expected_release=expected_release,
        expected_data_root_identity=(
            f"{data_metadata.st_dev}:{data_metadata.st_ino}"
            if expected_data_root_identity is None
            else expected_data_root_identity
        ),
        expected_uid=os.getuid() if expected_uid is None else expected_uid,
        expected_gid=os.getgid() if expected_gid is None else expected_gid,
    )


def test_preflight_accepts_the_same_real_directory_and_preserves_existing_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    receipt_path = receipt_dir / "external-backup.receipt.json"
    previous_receipt = b"previous-receipt\n"
    receipt_path.write_bytes(previous_receipt)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    probe_modes: list[int] = []
    real_fsync = module.os.fsync

    def inspect_fsync(file_descriptor: int) -> None:
        metadata = os.fstat(file_descriptor)
        if stat.S_ISREG(metadata.st_mode):
            probe_modes.append(stat.S_IMODE(metadata.st_mode))
        real_fsync(file_descriptor)

    monkeypatch.setattr(module.os, "fsync", inspect_fsync)

    _verify(module, data_root, receipt_dir)

    assert probe_modes == [0o600]
    assert receipt_path.read_bytes() == previous_receipt
    assert not list(receipt_dir.glob(PROBE_PATTERN))


def test_preflight_defaults_to_the_fixed_service_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getuid() == 10001 and os.getgid() == 10001:
        pytest.skip("synthetic directory already has the production identity")
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")

    with pytest.raises(module.PublisherPreflightError) as exc_info:
        module.verify_recovery_publisher(
            data_root,
            receipt_dir,
            expected_release="release-a",
            expected_data_root_identity=f"{data_root.stat().st_dev}:{data_root.stat().st_ino}",
        )

    assert exc_info.value.code == "invalid_identity"
    assert not list(receipt_dir.glob(PROBE_PATTERN))


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("wrong_owner", "invalid_identity"),
        ("wrong_mode", "invalid_mode"),
        ("missing_runtime", "invalid_data_path"),
        ("symlink_logs", "invalid_data_path"),
        ("symlink_runtime", "invalid_data_path"),
        ("mount_mismatch", "mount_mismatch"),
        ("root_identity_mismatch", "root_identity_mismatch"),
        ("release_mismatch", "release_mismatch"),
    ],
)
def test_preflight_rejects_invalid_publisher_contracts_without_probe_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_code: str,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    expected_uid = os.getuid()
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")

    if mutation == "wrong_owner":
        expected_uid += 1
    elif mutation == "wrong_mode":
        receipt_dir.chmod(0o750)
    elif mutation == "missing_runtime":
        receipt_dir.rmdir()
        receipt_dir = tmp_path / "other-receipts"
        receipt_dir.mkdir(mode=0o700)
    elif mutation == "symlink_logs":
        receipt_dir.rmdir()
        (data_root / "logs").rmdir()
        real_logs = tmp_path / "real-logs"
        receipt_dir = real_logs / "runtime"
        receipt_dir.mkdir(parents=True, mode=0o700)
        (data_root / "logs").symlink_to(real_logs, target_is_directory=True)
    elif mutation == "symlink_runtime":
        receipt_dir.rmdir()
        real_runtime = tmp_path / "real-runtime"
        real_runtime.mkdir(mode=0o700)
        (data_root / "logs" / "runtime").symlink_to(real_runtime, target_is_directory=True)
        receipt_dir = real_runtime
    elif mutation == "mount_mismatch":
        receipt_dir = tmp_path / "other-receipts"
        receipt_dir.mkdir(mode=0o700)
    elif mutation == "root_identity_mismatch":
        pass
    elif mutation == "release_mismatch":
        monkeypatch.setenv("NOVEL_RELEASE_ID", "other-release")

    with pytest.raises(module.PublisherPreflightError) as exc_info:
        _verify(
            module,
            data_root,
            receipt_dir,
            expected_uid=expected_uid,
            expected_data_root_identity=(
                "999999999:999999999" if mutation == "root_identity_mismatch" else None
            ),
        )

    assert exc_info.value.code == expected_code
    assert not list(tmp_path.rglob(PROBE_PATTERN))


def test_preflight_fails_closed_when_the_probe_cannot_be_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    real_open = module.os.open

    def fail_probe_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        if isinstance(path, str) and path.startswith(".recovery-publisher-probe-"):
            raise PermissionError("synthetic private path must not escape")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", fail_probe_open)

    with pytest.raises(module.PublisherPreflightError) as exc_info:
        _verify(module, data_root, receipt_dir)

    assert exc_info.value.code == "probe_failed"
    assert not list(receipt_dir.glob(PROBE_PATTERN))


def test_preflight_removes_and_directory_fsyncs_a_probe_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    real_fsync = module.os.fsync
    fsync_calls: list[str] = []

    def fail_probe_fsync(file_descriptor: int) -> None:
        metadata = os.fstat(file_descriptor)
        if stat.S_ISREG(metadata.st_mode):
            fsync_calls.append("probe")
            raise OSError("synthetic fsync failure")
        fsync_calls.append("directory")
        real_fsync(file_descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_probe_fsync)

    with pytest.raises(module.PublisherPreflightError) as exc_info:
        _verify(module, data_root, receipt_dir)

    assert exc_info.value.code == "probe_failed"
    assert fsync_calls == ["probe", "directory"]
    assert not list(receipt_dir.glob(PROBE_PATTERN))


def test_preflight_retries_partial_probe_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")
    real_write = module.os.write
    write_sizes: list[int] = []

    def partial_write(file_descriptor: int, payload: object) -> int:
        payload_length = len(payload)  # type: ignore[arg-type]
        limit = max(1, payload_length // 2)
        written = real_write(file_descriptor, payload[:limit])  # type: ignore[index]
        write_sizes.append(written)
        return written

    monkeypatch.setattr(module.os, "write", partial_write)

    _verify(module, data_root, receipt_dir)

    assert len(write_sizes) > 1
    assert sum(write_sizes) == len(module._PROBE_PAYLOAD)
    assert not list(receipt_dir.glob(PROBE_PATTERN))


@pytest.mark.parametrize(
    "failure_stage",
    ["zero_write", "close", "unlink", "directory_fsync"],
)
def test_preflight_fails_closed_and_cleans_probe_for_deterministic_io_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    module = _load_helper()
    data_root, receipt_dir = _prepare_layout(tmp_path)
    monkeypatch.setenv("NOVEL_RELEASE_ID", "release-a")

    if failure_stage == "zero_write":
        monkeypatch.setattr(module.os, "write", lambda _fd, _payload: 0)
    elif failure_stage == "close":
        real_close = module.os.close
        close_failed = False

        def fail_probe_close(file_descriptor: int) -> None:
            nonlocal close_failed
            metadata = os.fstat(file_descriptor)
            real_close(file_descriptor)
            if stat.S_ISREG(metadata.st_mode) and not close_failed:
                close_failed = True
                raise OSError("synthetic close failure")

        monkeypatch.setattr(module.os, "close", fail_probe_close)
    elif failure_stage == "unlink":
        real_unlink = module.os.unlink

        def fail_after_unlink(*args: object, **kwargs: object) -> None:
            real_unlink(*args, **kwargs)
            raise OSError("synthetic unlink failure")

        monkeypatch.setattr(module.os, "unlink", fail_after_unlink)
    else:
        real_fsync = module.os.fsync

        def fail_directory_fsync(file_descriptor: int) -> None:
            if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
                raise OSError("synthetic directory fsync failure")
            real_fsync(file_descriptor)

        monkeypatch.setattr(module.os, "fsync", fail_directory_fsync)

    with pytest.raises(module.PublisherPreflightError) as exc_info:
        _verify(module, data_root, receipt_dir)

    assert exc_info.value.code == "probe_failed"
    assert not list(receipt_dir.glob(PROBE_PATTERN))


def test_preflight_cli_emits_only_a_bounded_failure_message(tmp_path: Path) -> None:
    assert HELPER.is_file(), "recovery publisher preflight helper is missing"
    private_marker = "private-source-payload"
    private_root = tmp_path / private_marker
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--data-root",
            str(private_root),
            "--receipt-dir",
            str(private_root / "logs" / "runtime"),
            "--expected-release",
            private_marker,
            "--expected-data-root-identity",
            "1:1",
        ],
        cwd=ROOT,
        env={**os.environ, "NOVEL_RELEASE_ID": "wrong-release"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "recovery publisher preflight failed\n"
    assert private_marker not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert "Traceback" not in result.stderr
