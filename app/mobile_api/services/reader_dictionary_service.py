from __future__ import annotations

import gzip
import io
from collections.abc import Callable
from pathlib import Path, PurePosixPath
import zipfile


READER_OFFLINE_DICTIONARY_DIR = "dictionaries"
READER_OFFLINE_DICTIONARY_SUFFIXES = {".csv", ".dsl", ".json", ".jsonl", ".tsv", ".u8", ".txt"}
READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES = {".zip"}
MAX_READER_DICTIONARY_BYTES = 80 * 1024 * 1024
MAX_READER_DICTIONARY_ARCHIVE_FILES = 40

ReaderDictionaryFileRows = Callable[[Path], list[dict]]
ReaderDictionaryStardictRows = Callable[..., list[dict]]
ReaderDictionaryJsonlBytes = Callable[[list[dict]], bytes]


class ReaderDictionaryService:
    """Own Reader dictionary file validation, storage, archives, and lookup paths."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        file_rows: ReaderDictionaryFileRows,
        stardict_rows: ReaderDictionaryStardictRows,
        jsonl_bytes: ReaderDictionaryJsonlBytes,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._file_rows = file_rows
        self._stardict_rows = stardict_rows
        self._jsonl_bytes = jsonl_bytes

    @staticmethod
    def _safe_filename_part(value: str) -> str:
        return "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in value)

    def _dictionary_dir(self) -> Path:
        path = self.data_dir / READER_OFFLINE_DICTIONARY_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_dictionary_filename(self, filename: str) -> str:
        safe_name = self._safe_filename_part(Path(filename or "").name).strip("._-")
        if not safe_name:
            raise ValueError("Dictionary filename is required")
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in READER_OFFLINE_DICTIONARY_SUFFIXES:
            supported = ", ".join(sorted(READER_OFFLINE_DICTIONARY_SUFFIXES))
            raise ValueError(f"Unsupported dictionary format. Supported: {supported}")
        return safe_name

    def _safe_dictionary_archive_filename(self, filename: str) -> str:
        safe_name = self._safe_filename_part(Path(filename or "").name).strip("._-")
        if not safe_name:
            raise ValueError("Dictionary filename is required")
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES:
            supported = ", ".join(sorted(READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES))
            raise ValueError(f"Unsupported dictionary archive format. Supported: {supported}")
        return safe_name

    def _dictionary_payload(self, path: Path) -> dict:
        return {
            "filename": path.name,
            "entry_count": len(self._file_rows(path)),
            "size_bytes": path.stat().st_size,
        }

    def list_reader_dictionaries(self) -> list[dict]:
        dictionaries_dir = self._dictionary_dir()
        payloads: list[dict] = []
        for path in sorted(dictionaries_dir.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.casefold() in READER_OFFLINE_DICTIONARY_SUFFIXES:
                payloads.append(self._dictionary_payload(path))
        return payloads

    def _write_dictionary_file(self, *, safe_name: str, content: bytes) -> dict:
        if not content:
            raise ValueError("Dictionary file is empty")
        if len(content) > MAX_READER_DICTIONARY_BYTES:
            raise ValueError("Dictionary file is too large")

        target = self._dictionary_dir() / safe_name
        temp = target.with_name(f".{target.stem}.upload{target.suffix}")
        temp.write_bytes(content)
        entry_count = len(self._file_rows(temp))
        if entry_count <= 0:
            temp.unlink(missing_ok=True)
            raise ValueError("Dictionary file contains no readable entries")
        temp.replace(target)
        return {
            "filename": target.name,
            "entry_count": entry_count,
            "size_bytes": target.stat().st_size,
        }

    @staticmethod
    def _zip_member_basename(filename: str) -> str | None:
        member_path = PurePosixPath(filename)
        if member_path.is_absolute() or any(part == ".." for part in member_path.parts):
            return None
        return member_path.name or None

    def _save_dictionary_archive(self, *, filename: str, content: bytes) -> dict:
        safe_archive_name = self._safe_dictionary_archive_filename(filename)
        extracted: list[dict] = []
        seen_names: set[str] = set()

        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise ValueError("Dictionary archive is not a valid ZIP file") from exc

        with archive:
            file_members = [member for member in archive.infolist() if not member.is_dir()]
            if len(file_members) > MAX_READER_DICTIONARY_ARCHIVE_FILES:
                raise ValueError(
                    f"Dictionary archive contains too many files; max {MAX_READER_DICTIONARY_ARCHIVE_FILES}"
                )

            stardict_groups: dict[str, dict[str, bytes]] = {}
            for member in file_members:
                member_path = PurePosixPath(member.filename)
                if (
                    member_path.is_absolute()
                    or any(part == ".." for part in member_path.parts)
                    or not member_path.name
                ):
                    continue
                member_name = str(member_path)
                lowered_name = member_name.casefold()
                if lowered_name.endswith(".dict.dz"):
                    suffix = ".dict.dz"
                    group_key = member_name[: -len(".dict.dz")]
                    part_key = ".dict"
                else:
                    suffix = member_path.suffix.casefold()
                    group_key = str(member_path.with_suffix(""))
                    part_key = suffix
                if suffix not in {".dict", ".dict.dz", ".idx", ".ifo"}:
                    continue
                if member.file_size <= 0:
                    continue
                if member.file_size > MAX_READER_DICTIONARY_BYTES:
                    raise ValueError(f"StarDict file inside archive is too large: {member_path.name}")
                content_bytes = archive.read(member)
                if len(content_bytes) > MAX_READER_DICTIONARY_BYTES:
                    raise ValueError(f"StarDict file inside archive is too large: {member_path.name}")
                if suffix == ".dict.dz":
                    try:
                        content_bytes = gzip.decompress(content_bytes)
                    except (OSError, EOFError) as exc:
                        raise ValueError(f"StarDict compressed dictionary is invalid: {member_path.name}") from exc
                    if len(content_bytes) > MAX_READER_DICTIONARY_BYTES:
                        raise ValueError(f"StarDict file inside archive is too large: {member_path.name}")
                stardict_groups.setdefault(group_key, {})[part_key] = content_bytes

            for group_key, parts in stardict_groups.items():
                if not {".dict", ".idx", ".ifo"}.issubset(parts):
                    continue
                safe_stem = self._safe_filename_part(PurePosixPath(group_key).name).strip("._-") or "stardict"
                safe_member_name = self._safe_dictionary_filename(f"{safe_stem}.stardict.jsonl")
                if safe_member_name in seen_names:
                    continue
                rows = self._stardict_rows(
                    ifo_content=parts[".ifo"],
                    idx_content=parts[".idx"],
                    dict_content=parts[".dict"],
                )
                if not rows:
                    continue
                try:
                    extracted.append(
                        self._write_dictionary_file(
                            safe_name=safe_member_name,
                            content=self._jsonl_bytes(rows),
                        )
                    )
                    seen_names.add(safe_member_name)
                except ValueError:
                    continue

            for member in file_members:
                basename = self._zip_member_basename(member.filename)
                if not basename:
                    continue
                try:
                    safe_member_name = self._safe_dictionary_filename(basename)
                except ValueError:
                    continue
                if safe_member_name in seen_names:
                    continue
                if member.file_size <= 0:
                    continue
                if member.file_size > MAX_READER_DICTIONARY_BYTES:
                    raise ValueError(f"Dictionary file inside archive is too large: {safe_member_name}")

                member_content = archive.read(member)
                if len(member_content) > MAX_READER_DICTIONARY_BYTES:
                    raise ValueError(f"Dictionary file inside archive is too large: {safe_member_name}")
                try:
                    extracted.append(
                        self._write_dictionary_file(
                            safe_name=safe_member_name,
                            content=member_content,
                        )
                    )
                    seen_names.add(safe_member_name)
                except ValueError:
                    continue

        extracted = sorted(extracted, key=lambda item: item["filename"].casefold())
        if not extracted:
            raise ValueError("Dictionary archive contains no readable dictionary files")
        return {
            "filename": safe_archive_name,
            "entry_count": sum(int(item["entry_count"]) for item in extracted),
            "file_count": len(extracted),
            "files": extracted,
            "size_bytes": len(content),
        }

    def save_reader_dictionary(self, *, filename: str, content: bytes) -> dict:
        if not content:
            raise ValueError("Dictionary file is empty")
        if len(content) > MAX_READER_DICTIONARY_BYTES:
            raise ValueError("Dictionary file is too large")

        if Path(filename or "").suffix.casefold() in READER_OFFLINE_DICTIONARY_ARCHIVE_SUFFIXES:
            return self._save_dictionary_archive(filename=filename, content=content)

        safe_name = self._safe_dictionary_filename(filename)
        return self._write_dictionary_file(safe_name=safe_name, content=content)

    def delete_reader_dictionary(self, filename: str) -> bool:
        safe_name = self._safe_dictionary_filename(filename)
        target = self._dictionary_dir() / safe_name
        if not target.exists() or not target.is_file():
            return False
        target.unlink()
        return True

    def get_reader_dictionary_path(self, filename: str) -> Path | None:
        raw_name = (filename or "").strip()
        if not raw_name or "/" in raw_name or "\\" in raw_name:
            raise ValueError("Dictionary filename must not include paths")
        safe_name = self._safe_dictionary_filename(raw_name)
        target = self._dictionary_dir() / safe_name
        if not target.exists() or not target.is_file():
            return None
        return target
