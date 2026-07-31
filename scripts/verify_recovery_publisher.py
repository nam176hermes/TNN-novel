#!/usr/bin/env python3
"""Fail-closed recovery receipt publisher preflight."""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import secrets
import stat
import sys


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
_PROBE_OPEN_FLAGS = os.O_WRONLY | os.O_CLOEXEC | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_PROBE_PREFIX = ".recovery-publisher-probe-"
_PROBE_PAYLOAD = b"recovery-publisher-preflight\n"


class PublisherPreflightError(RuntimeError):
    """A bounded recovery publisher contract failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _open_directory(path: str, *, dir_fd: int | None = None) -> int:
    try:
        return os.open(path, _DIRECTORY_OPEN_FLAGS, dir_fd=dir_fd)
    except OSError:
        raise PublisherPreflightError("invalid_data_path") from None


def _exercise_writable_probe(receipt_fd: int) -> None:
    probe_name = f"{_PROBE_PREFIX}{secrets.token_hex(16)}"
    probe_fd: int | None = None
    probe_created = False
    failed = False
    previous_umask = os.umask(0o077)
    try:
        try:
            probe_fd = os.open(probe_name, _PROBE_OPEN_FLAGS, 0o600, dir_fd=receipt_fd)
            probe_created = True
            metadata = os.fstat(probe_fd)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                failed = True
            else:
                view = memoryview(_PROBE_PAYLOAD)
                while view:
                    written = os.write(probe_fd, view)
                    if written <= 0:
                        raise OSError("probe write failed")
                    view = view[written:]
                os.fsync(probe_fd)
        except (OSError, PublisherPreflightError):
            failed = True
    finally:
        os.umask(previous_umask)
        if probe_fd is not None:
            try:
                os.close(probe_fd)
            except OSError:
                failed = True
        if probe_created:
            try:
                os.unlink(probe_name, dir_fd=receipt_fd)
            except OSError:
                failed = True
            try:
                os.fsync(receipt_fd)
            except OSError:
                failed = True
    if failed:
        raise PublisherPreflightError("probe_failed")


def verify_recovery_publisher(
    data_root: Path,
    receipt_dir: Path,
    *,
    expected_release: str,
    expected_data_root_identity: str,
    expected_uid: int = 10001,
    expected_gid: int = 10001,
) -> None:
    """Verify the image identity and the fixed writable receipt directory."""

    if not expected_release or os.environ.get("NOVEL_RELEASE_ID", "") != expected_release:
        raise PublisherPreflightError("release_mismatch")
    try:
        importlib.import_module("scripts.record_restore_drill_status")
    except Exception:
        raise PublisherPreflightError("image_contract") from None
    identity_parts = expected_data_root_identity.split(":")
    if (
        len(identity_parts) != 2
        or not identity_parts[0].isdecimal()
        or not identity_parts[1].isdecimal()
    ):
        raise PublisherPreflightError("invalid_expected_identity")

    descriptors: list[int] = []
    try:
        data_fd = _open_directory(os.fspath(data_root))
        descriptors.append(data_fd)
        try:
            data_metadata = os.fstat(data_fd)
        except OSError:
            raise PublisherPreflightError("invalid_data_path") from None
        actual_data_root_identity = f"{data_metadata.st_dev}:{data_metadata.st_ino}"
        if actual_data_root_identity != expected_data_root_identity:
            raise PublisherPreflightError("root_identity_mismatch")
        logs_fd = _open_directory("logs", dir_fd=data_fd)
        descriptors.append(logs_fd)
        runtime_fd = _open_directory("runtime", dir_fd=logs_fd)
        descriptors.append(runtime_fd)
        receipt_fd = _open_directory(os.fspath(receipt_dir))
        descriptors.append(receipt_fd)

        try:
            runtime_metadata = os.fstat(runtime_fd)
            receipt_metadata = os.fstat(receipt_fd)
        except OSError:
            raise PublisherPreflightError("invalid_data_path") from None
        if (runtime_metadata.st_dev, runtime_metadata.st_ino) != (
            receipt_metadata.st_dev,
            receipt_metadata.st_ino,
        ):
            raise PublisherPreflightError("mount_mismatch")
        if runtime_metadata.st_uid != expected_uid or runtime_metadata.st_gid != expected_gid:
            raise PublisherPreflightError("invalid_identity")
        if stat.S_IMODE(runtime_metadata.st_mode) != 0o700:
            raise PublisherPreflightError("invalid_mode")

        _exercise_writable_probe(receipt_fd)
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--expected-data-root-identity", required=True)
    args = parser.parse_args()
    try:
        verify_recovery_publisher(
            args.data_root,
            args.receipt_dir,
            expected_release=args.expected_release,
            expected_data_root_identity=args.expected_data_root_identity,
        )
    except PublisherPreflightError:
        print("recovery publisher preflight failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
