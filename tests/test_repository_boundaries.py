"""Ownership contracts for the repositories behind db.py's public facade."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.database import (book_repository, db, glossary_repository, import_repository,
                          job_repository, user_repository)
from app.database.connection import get_connection
from app.ingestion import import_metadata
from app.jobs import states
from app.mobile_api import job_states
from app.mobile_api.services import import_metadata as legacy_import_metadata


REPOSITORIES = (book_repository, glossary_repository, import_repository, job_repository, user_repository)


def test_db_facade_reexports_canonical_repository_functions_and_types() -> None:
    for repository in REPOSITORIES:
        assert repository.get_connection is get_connection
        for name, value in vars(repository).items():
            if (inspect.isfunction(value) or inspect.isclass(value)) and value.__module__ == repository.__name__:
                assert getattr(db, name) is value, name


def test_database_domains_do_not_import_api_or_compatibility_facade() -> None:
    for module in (db, *REPOSITORIES):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(name.startswith("app.mobile_api") for name in imported), module.__name__
        if module is not db:
            assert "app.database.db" not in imported, module.__name__


def test_legacy_api_helpers_reexport_domain_rules_without_duplicate_implementations() -> None:
    assert legacy_import_metadata.detect_import_metadata is import_metadata.detect_import_metadata
    assert legacy_import_metadata.normalize_book_key is import_metadata.normalize_book_key
    assert job_states.normalize_job_state is states.normalize_job_state
    assert job_states.is_valid_job_state_transition is states.is_valid_job_state_transition
