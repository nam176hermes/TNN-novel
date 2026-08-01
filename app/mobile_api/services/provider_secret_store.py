from __future__ import annotations

import fcntl
import json
import os
import secrets
import stat
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


STORE_VERSION = 2
LEGACY_STORE_VERSION = 1
STORE_FILENAME = "provider-keys.json"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
PROVIDER_ENV_NAMES = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    }
)
_STORE_LOCK = threading.RLock()
_OPEN_COMMON = (
    getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


class ProviderSecretStoreError(RuntimeError):
    """A sanitized provider secret-store failure."""


@dataclass(frozen=True)
class ProviderSecretStoreMutation:
    committed: bool
    durable: bool

    def require_durable(self) -> None:
        if not self.committed or not self.durable:
            raise ProviderSecretStoreError("Provider secret store durability is unconfirmed")


@dataclass(frozen=True)
class _ProviderSecretState:
    keys: dict[str, str]
    deleted: frozenset[str]


def provider_secret_store_path() -> Path:
    try:
        configured = os.getenv("PROVIDER_SECRET_STORE_PATH", "").strip()
        if configured:
            return Path(configured).expanduser()

        configured_home = os.getenv("XDG_CONFIG_HOME", "").strip()
        config_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".config"
        if not config_home.is_absolute():
            config_home = Path.home() / ".config"
        return config_home / "novel-tnn" / STORE_FILENAME
    except (OSError, RuntimeError):
        raise ProviderSecretStoreError("Provider secret store path is unavailable") from None


def _valid_secret_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\n" not in value
        and "\r" not in value
        and "\0" not in value
    )


def _parse_state(payload: object) -> _ProviderSecretState:
    if not isinstance(payload, dict):
        raise ProviderSecretStoreError("Provider secret store is malformed")

    version = payload.get("version")
    if version == LEGACY_STORE_VERSION and set(payload) == {"version", "keys"}:
        raw_deleted: object = []
    elif version == STORE_VERSION and set(payload) == {"version", "keys", "deleted"}:
        raw_deleted = payload.get("deleted")
    else:
        raise ProviderSecretStoreError("Provider secret store is malformed")

    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, dict) or not isinstance(raw_deleted, list):
        raise ProviderSecretStoreError("Provider secret store is malformed")

    keys: dict[str, str] = {}
    for key, value in raw_keys.items():
        if key not in PROVIDER_ENV_NAMES or not _valid_secret_value(value):
            raise ProviderSecretStoreError("Provider secret store is malformed")
        keys[key] = value

    if (
        any(not isinstance(key, str) or key not in PROVIDER_ENV_NAMES for key in raw_deleted)
        or len(raw_deleted) != len(set(raw_deleted))
        or set(raw_deleted).intersection(keys)
    ):
        raise ProviderSecretStoreError("Provider secret store is malformed")
    return _ProviderSecretState(keys=keys, deleted=frozenset(raw_deleted))


class ProviderSecretStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.name or self.path.name in {".", ".."}:
            raise ProviderSecretStoreError("Provider secret store is unsafe")

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.lock")

    def _open_directory(self) -> int:
        directory = self.path.parent
        try:
            if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
                raise ProviderSecretStoreError("Provider secret store is unsafe")
            directory.mkdir(parents=True, mode=DIRECTORY_MODE, exist_ok=True)
            metadata = directory.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink():
                raise ProviderSecretStoreError("Provider secret store is unsafe")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            descriptor = os.open(directory, flags)
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise ProviderSecretStoreError("Provider secret store is unsafe")
            os.fchmod(descriptor, DIRECTORY_MODE)
            return descriptor
        except ProviderSecretStoreError:
            raise
        except OSError as exc:
            raise ProviderSecretStoreError("Provider secret store is unavailable") from exc

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        with _STORE_LOCK:
            directory_descriptor = self._open_directory()
            lock_descriptor = -1
            try:
                flags = os.O_RDWR | os.O_CREAT | _OPEN_COMMON
                try:
                    lock_descriptor = os.open(
                        self.lock_path.name,
                        flags,
                        FILE_MODE,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ProviderSecretStoreError("Provider secret store is unsafe") from exc
                if not stat.S_ISREG(os.fstat(lock_descriptor).st_mode):
                    raise ProviderSecretStoreError("Provider secret store is unsafe")
                os.fchmod(lock_descriptor, FILE_MODE)
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
                yield directory_descriptor
            except ProviderSecretStoreError:
                raise
            except OSError as exc:
                raise ProviderSecretStoreError("Provider secret store is unavailable") from exc
            finally:
                if lock_descriptor >= 0:
                    with suppress(OSError):
                        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                    with suppress(OSError):
                        os.close(lock_descriptor)
                with suppress(OSError):
                    os.close(directory_descriptor)

    def _read_state_locked(self, directory_descriptor: int) -> _ProviderSecretState:
        descriptor = -1
        try:
            descriptor = os.open(
                self.path.name,
                os.O_RDONLY | _OPEN_COMMON,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            return _ProviderSecretState(keys={}, deleted=frozenset())
        except OSError as exc:
            raise ProviderSecretStoreError("Provider secret store is unsafe") from exc

        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ProviderSecretStoreError("Provider secret store is unsafe")
            os.fchmod(descriptor, FILE_MODE)
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
                descriptor = -1
                payload = json.load(handle)
        except ProviderSecretStoreError:
            raise
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ProviderSecretStoreError("Provider secret store is malformed") from exc
        except (OSError, UnicodeError) as exc:
            raise ProviderSecretStoreError("Provider secret store is unavailable") from exc
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
        return _parse_state(payload)

    def _check_destination_locked(self, directory_descriptor: int) -> None:
        try:
            metadata = os.stat(
                self.path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProviderSecretStoreError("Provider secret store is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ProviderSecretStoreError("Provider secret store is unsafe")

    def _open_temporary_locked(self, directory_descriptor: int) -> tuple[int, str]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_COMMON
        for _attempt in range(32):
            temporary_name = f".provider-keys.{secrets.token_hex(16)}.tmp"
            try:
                descriptor = os.open(
                    temporary_name,
                    flags,
                    FILE_MODE,
                    dir_fd=directory_descriptor,
                )
            except FileExistsError:
                continue
            except OSError as exc:
                raise ProviderSecretStoreError("Provider secret store is unavailable") from exc
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise ProviderSecretStoreError("Provider secret store is unsafe")
            os.fchmod(descriptor, FILE_MODE)
            return descriptor, temporary_name
        raise ProviderSecretStoreError("Provider secret store is unavailable")

    def _write_state_locked(
        self,
        directory_descriptor: int,
        state: _ProviderSecretState,
    ) -> ProviderSecretStoreMutation:
        self._check_destination_locked(directory_descriptor)
        descriptor = -1
        temporary_name: str | None = None
        committed = False
        primary_error: ProviderSecretStoreError | None = None
        try:
            descriptor, temporary_name = self._open_temporary_locked(directory_descriptor)
            payload = {
                "version": STORE_VERSION,
                "keys": dict(sorted(state.keys.items())),
                "deleted": sorted(state.deleted),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
                descriptor = -1
                json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                self.path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            committed = True
            temporary_name = None
        except ProviderSecretStoreError as exc:
            primary_error = exc
        except (OSError, TypeError, ValueError) as exc:
            primary_error = ProviderSecretStoreError("Provider secret store is unavailable")
            primary_error.__cause__ = exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if primary_error is None:
                        primary_error = ProviderSecretStoreError(
                            "Provider secret store is unavailable"
                        )
                        primary_error.__cause__ = exc
            if temporary_name is not None and not committed:
                try:
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    cleanup_error = ProviderSecretStoreError(
                        "Provider secret store cleanup failed"
                    )
                    cleanup_error.__cause__ = exc
                    raise cleanup_error from primary_error

        if primary_error is not None:
            raise primary_error

        try:
            os.fsync(directory_descriptor)
        except OSError:
            return ProviderSecretStoreMutation(committed=True, durable=False)
        return ProviderSecretStoreMutation(committed=True, durable=True)

    def load(self) -> dict[str, str]:
        with self._locked_directory() as directory_descriptor:
            return dict(self._read_state_locked(directory_descriptor).keys)

    def save(self, key: str, value: str) -> ProviderSecretStoreMutation:
        if key not in PROVIDER_ENV_NAMES or not _valid_secret_value(value):
            raise ProviderSecretStoreError("Provider secret value is invalid")
        with self._locked_directory() as directory_descriptor:
            state = self._read_state_locked(directory_descriptor)
            keys = dict(state.keys)
            keys[key] = value
            deleted = set(state.deleted)
            deleted.discard(key)
            return self._write_state_locked(
                directory_descriptor,
                _ProviderSecretState(keys=keys, deleted=frozenset(deleted)),
            )

    def delete(self, key: str) -> ProviderSecretStoreMutation:
        if key not in PROVIDER_ENV_NAMES:
            raise ProviderSecretStoreError("Provider secret value is invalid")
        with self._locked_directory() as directory_descriptor:
            state = self._read_state_locked(directory_descriptor)
            keys = dict(state.keys)
            keys.pop(key, None)
            deleted = set(state.deleted)
            deleted.add(key)
            return self._write_state_locked(
                directory_descriptor,
                _ProviderSecretState(keys=keys, deleted=frozenset(deleted)),
            )

    def load_into_environment(self) -> tuple[str, ...]:
        with self._locked_directory() as directory_descriptor:
            state = self._read_state_locked(directory_descriptor)
        for key in state.deleted:
            os.environ.pop(key, None)
        for key, value in state.keys.items():
            os.environ[key] = value
        return tuple(sorted(state.keys))
