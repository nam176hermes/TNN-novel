from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from app.database.connection import get_connection
from app.database.glossary_repository import normalize_source_key
from app.translation import styleguide_config


EFFECTIVE_MODES = {"translate", "transliterate", "context"}
EXACT_MODES = {"translate", "transliterate"}


def _split_variants(value: str | None) -> list[str]:
    normalized = str(value or "")
    for separator in ("|", "/", ",", "，", ";", "；", "\n", "\r"):
        normalized = normalized.replace(separator, "|")
    return list(dict.fromkeys(part.strip() for part in normalized.split("|") if part.strip()))


def _target_key(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _style_profile(conn, profile_id: str | None) -> dict | None:
    if profile_id:
        row = conn.execute("SELECT * FROM style_profiles WHERE id = ?", (profile_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM style_profiles WHERE is_default = 1 LIMIT 1").fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM style_profiles ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def _styleguide_rows(genre: str | None) -> list[dict]:
    rows: list[dict] = []
    for index, term in enumerate(styleguide_config.get_locked_terms()):
        term_genre = str(term.get("genre") or "").strip()
        if genre and term_genre and term_genre != genre:
            continue
        source = str(term.get("source") or "").strip()
        target = str(term.get("target") or "").strip()
        mode = str(term.get("mode") or "translate").strip()
        if not source or not target or mode not in EFFECTIVE_MODES:
            continue
        rows.append(
            {
                "id": -100000 - index,
                "book_id": 0,
                "source_term": source,
                "source_key": normalize_source_key(source),
                "target_term": target,
                "category": str(term.get("term_type") or "term"),
                "approved": 1,
                "review_status": "LOCKED",
                "locked": 1,
                "mode": mode,
                "pinyin": str(term.get("pinyin") or ""),
                "notes_vi": str(term.get("note") or ""),
                "variants": str(term.get("variants") or ""),
                "priority": int(term.get("priority") or 0),
                "genre": term_genre,
                "term_type": str(term.get("term_type") or "term"),
                "version": 1,
                "archived_at": "",
                "styleguide": True,
            }
        )
    return rows


@dataclass(frozen=True)
class EffectiveGlossary:
    book_id: int
    fingerprint: str
    style_profile: Mapping[str, object] | None
    style_revision: str
    prompt_mapping: Mapping[str, str]
    translate_mapping: Mapping[str, str]
    name_mapping: Mapping[str, str]
    prompt_terms: tuple[Mapping[str, object], ...]
    exact_terms: tuple[Mapping[str, object], ...]
    locked_terms: tuple[Mapping[str, object], ...]
    dictionary_terms: tuple[Mapping[str, object], ...]
    reserved_source_keys: frozenset[str]

    def mapping_for_mode(self, mode: str) -> Mapping[str, str]:
        return MappingProxyType(
            {
                str(term["source_term"]): str(term["target_term"])
                for term in self.prompt_terms
                if term["mode"] == mode
            }
        )


def resolve_effective_glossary(
    db_path: Path,
    book_id: int = 0,
    *,
    style_profile_id: str | None = None,
) -> EffectiveGlossary:
    """Resolve the one effective runtime view of approved glossary state."""
    with get_connection(db_path) as conn:
        profile = _style_profile(conn, style_profile_id)
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM glossary_terms
                WHERE book_id IN (0, ?)
                  AND review_status IN ('APPROVED', 'LOCKED')
                  AND COALESCE(archived_at, '') = ''
                  AND source_term != ''
                  AND target_term != ''
                  AND mode IN ('translate', 'transliterate', 'context')
                ORDER BY id
                """,
                (book_id,),
            ).fetchall()
        ]

    genre = str(profile.get("id") or "") if profile else None
    database_source_keys = {
        normalize_source_key(surface)
        for row in rows
        for surface in [str(row["source_term"]), *_split_variants(row.get("variants"))]
        if normalize_source_key(surface)
    }
    book_primary_keys = {
        str(row.get("source_key") or normalize_source_key(row["source_term"]))
        for row in rows
        if int(row.get("book_id") or 0) == int(book_id) and int(book_id) != 0
    }
    candidates: list[dict] = []
    for row in [*rows, *_styleguide_rows(None)]:
        scope = int(row.get("book_id") or 0)
        source_key = str(row.get("source_key") or normalize_source_key(row["source_term"]))
        if scope == 0 and not row.get("styleguide") and source_key in book_primary_keys:
            continue
        styleguide = bool(row.get("styleguide"))
        surfaces = [
            (False, str(row["source_term"])),
            *((True, value) for value in _split_variants(row.get("variants"))),
        ]
        for is_variant, surface in surfaces:
            # Required DB precedence is 40 > 30 > 20 > 10. The legacy
            # styleguide stays below explicit global primaries but above variants.
            rank = (
                40 if scope == book_id and book_id != 0 and not is_variant
                else 30 if scope == book_id and book_id != 0
                else 20 if not styleguide and not is_variant
                else 10 if not styleguide
                else 15 if not is_variant
                else 14
            )
            candidates.append(
                {
                    "key": normalize_source_key(surface),
                    "surface": surface,
                    "rank": rank,
                    "is_variant": is_variant,
                    "row": row,
                }
            )

    selected: list[dict] = []
    by_key: dict[str, list[dict]] = {}
    for candidate in candidates:
        if candidate["key"]:
            by_key.setdefault(candidate["key"], []).append(candidate)
    for key in sorted(by_key):
        group = by_key[key]
        top_rank = max(candidate["rank"] for candidate in group)
        top = [candidate for candidate in group if candidate["rank"] == top_rank]
        if len({_target_key(candidate["row"]["target_term"]) for candidate in top}) > 1:
            continue
        selected.append(
            min(
                top,
                key=lambda candidate: (
                    -int(candidate["row"].get("locked") or 0),
                    -int(candidate["row"].get("priority") or 0),
                    int(candidate["row"]["id"]),
                    candidate["surface"],
                ),
            )
        )

    flattened: list[dict] = []
    for candidate in selected:
        term = dict(candidate["row"])
        term["canonical_source_term"] = term["source_term"]
        term["source_term"] = candidate["surface"]
        term["is_variant"] = candidate["is_variant"]
        flattened.append(term)
    flattened.sort(
        key=lambda term: (
            -int(term.get("locked") or 0),
            -int(term.get("book_id") or 0),
            -int(term.get("priority") or 0),
            -len(str(term["source_term"])),
            str(term["source_term"]),
        )
    )

    dictionary_terms: list[dict] = []
    by_id: dict[int, list[dict]] = {}
    for term in flattened:
        by_id.setdefault(int(term["id"]), []).append(term)
    for term_id in sorted(by_id):
        effective = by_id[term_id]
        primary = next((term for term in effective if not term["is_variant"]), effective[0])
        item = dict(primary)
        item["variants"] = "|".join(
            term["source_term"] for term in effective if term["source_term"] != primary["source_term"]
        )
        dictionary_terms.append(item)

    relevant = sorted(
        {
            (
                int(term["id"]),
                int(term.get("version") or 0),
                str(term["mode"]),
                str(term["target_term"]),
            )
            for term in flattened
        }
    )
    style_revision = f"{profile.get('id')}:{int(profile.get('revision') or 0)}" if profile else ""
    fingerprint = hashlib.sha256(
        json.dumps(
            {"terms": relevant, "style_revision": style_revision},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    prompt_mapping = {term["source_term"]: term["target_term"] for term in flattened}
    frozen_terms = tuple(_deep_freeze(term) for term in flattened)
    exact_terms = tuple(term for term in frozen_terms if term["mode"] in EXACT_MODES)
    locked_terms = tuple(
        term
        for term in exact_terms
        if int(term.get("locked") or 0) == 1
        and (
            not genre
            or not term.get("genre")
            or term.get("genre") == genre
        )
    )
    return EffectiveGlossary(
        book_id=book_id,
        fingerprint=fingerprint,
        style_profile=_deep_freeze(profile) if profile is not None else None,
        style_revision=style_revision,
        prompt_mapping=_deep_freeze(prompt_mapping),
        translate_mapping=_deep_freeze({
            str(term["source_term"]): str(term["target_term"])
            for term in exact_terms
            if term["mode"] == "translate"
        }),
        name_mapping=_deep_freeze({
            str(term["source_term"]): str(term["target_term"])
            for term in exact_terms
            if term["mode"] == "transliterate"
        }),
        prompt_terms=frozen_terms,
        exact_terms=exact_terms,
        locked_terms=locked_terms,
        dictionary_terms=tuple(_deep_freeze(term) for term in dictionary_terms),
        reserved_source_keys=frozenset(database_source_keys),
    )
