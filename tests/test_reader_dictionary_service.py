from __future__ import annotations

import inspect
import io
from pathlib import Path
import re
import zipfile

import pytest

import app.mobile_api.services.pipeline_service as pipeline_service_module
from app.mobile_api.services.pipeline_service import PipelineService
from app.mobile_api.services.reader_dictionary_service import ReaderDictionaryService


def make_pipeline(data_dir: Path) -> PipelineService:
    pipeline = object.__new__(PipelineService)
    pipeline.data_dir = data_dir
    return pipeline


def make_reader_dictionary_service(data_dir: Path) -> ReaderDictionaryService:
    return ReaderDictionaryService(
        data_dir=data_dir,
        file_rows=pipeline_service_module._reader_dictionary_file_rows,
        stardict_rows=pipeline_service_module._reader_dictionary_rows_from_stardict_bytes,
        jsonl_bytes=pipeline_service_module._reader_dictionary_jsonl_bytes,
    )


def test_extracted_reader_dictionary_service_owns_file_lifecycle(tmp_path: Path) -> None:
    service = make_reader_dictionary_service(tmp_path)
    content = b"term\ttarget\nsource\ttarget\n"

    saved = service.save_reader_dictionary(filename="reader_terms.tsv", content=content)

    assert service.list_reader_dictionaries() == [saved]
    assert service.get_reader_dictionary_path("reader_terms.tsv") == tmp_path / "dictionaries" / "reader_terms.tsv"
    assert service.delete_reader_dictionary("reader_terms.tsv") is True
    assert service.list_reader_dictionaries() == []


def test_pipeline_reader_dictionary_public_signatures_remain_stable() -> None:
    list_signature = inspect.signature(PipelineService.list_reader_dictionaries)
    save_signature = inspect.signature(PipelineService.save_reader_dictionary)
    delete_signature = inspect.signature(PipelineService.delete_reader_dictionary)
    path_signature = inspect.signature(PipelineService.get_reader_dictionary_path)

    assert list(list_signature.parameters) == ["self"]
    assert list(save_signature.parameters) == ["self", "filename", "content"]
    assert save_signature.parameters["filename"].kind is inspect.Parameter.KEYWORD_ONLY
    assert save_signature.parameters["content"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(delete_signature.parameters) == ["self", "filename"]
    assert list(path_signature.parameters) == ["self", "filename"]


def test_pipeline_reader_dictionary_file_lifecycle_payloads_are_stable(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    content = "term\ttarget\tdefinition\n道心\tđạo tâm\tTâm cảnh tu đạo.\n".encode()

    saved = pipeline.save_reader_dictionary(filename="reader_terms.tsv", content=content)

    assert saved == {
        "filename": "reader_terms.tsv",
        "entry_count": 1,
        "size_bytes": len(content),
    }
    assert pipeline.list_reader_dictionaries() == [saved]

    path = pipeline.get_reader_dictionary_path("reader_terms.tsv")
    assert path == tmp_path / "dictionaries" / "reader_terms.tsv"
    assert path.read_bytes() == content

    assert pipeline.delete_reader_dictionary("reader_terms.tsv") is True
    assert pipeline.get_reader_dictionary_path("reader_terms.tsv") is None
    assert pipeline.delete_reader_dictionary("reader_terms.tsv") is False


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda pipeline: pipeline.save_reader_dictionary(filename="", content=b"x"), "Dictionary filename is required"),
        (
            lambda pipeline: pipeline.save_reader_dictionary(filename="notes.md", content=b"x"),
            "Unsupported dictionary format. Supported: .csv, .dsl, .json, .jsonl, .tsv, .txt, .u8",
        ),
        (lambda pipeline: pipeline.save_reader_dictionary(filename="terms.tsv", content=b""), "Dictionary file is empty"),
        (
            lambda pipeline: pipeline.get_reader_dictionary_path("../terms.tsv"),
            "Dictionary filename must not include paths",
        ),
    ],
)
def test_pipeline_reader_dictionary_validation_messages_are_stable(
    tmp_path: Path,
    operation,
    message: str,
) -> None:
    pipeline = make_pipeline(tmp_path)

    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        operation(pipeline)


def test_pipeline_reader_dictionary_archive_filters_unsafe_members(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    archive = io.BytesIO()
    valid_content = b"term\ttarget\n\xe9\x81\x93\xe5\xbf\x83\tdao tam\n"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("nested/reader_terms.tsv", valid_content)
        zip_file.writestr("../escape.tsv", b"term\ttarget\nunsafe\tescape\n")
        zip_file.writestr("notes/readme.md", b"not a dictionary")

    saved = pipeline.save_reader_dictionary(filename="reader_pack.zip", content=archive.getvalue())

    assert saved["filename"] == "reader_pack.zip"
    assert saved["entry_count"] == 1
    assert saved["file_count"] == 1
    assert saved["files"] == [
        {
            "filename": "reader_terms.tsv",
            "entry_count": 1,
            "size_bytes": len(valid_content),
        }
    ]
    assert (tmp_path / "dictionaries" / "reader_terms.tsv").read_bytes() == valid_content
    assert not (tmp_path / "escape.tsv").exists()
