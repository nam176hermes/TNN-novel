from __future__ import annotations

import json
from contextlib import nullcontext
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.connection import get_connection

def _reader_progress_from_row(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    anchor = {}
    if "anchor_json" in row.keys():
        try:
            parsed_anchor = json.loads(row["anchor_json"] or "{}")
            if isinstance(parsed_anchor, dict):
                anchor = parsed_anchor
        except json.JSONDecodeError:
            anchor = {}
    return {
        "book_id": row["book_id"],
        "chapter_id": row["chapter_id"],
        "chapter_number": row["chapter_number"],
        "chapter_title": row["chapter_title"] or "",
        "mode": row["mode"] or "scroll",
        "percent": row["percent"] or 0,
        "paragraph_index": row["paragraph_index"] or 0,
        "char_offset": row["char_offset"] or 0,
        "absolute_char_offset": row["absolute_char_offset"] or 0,
        "page_index": row["page_index"] or 0,
        "anchor": anchor,
        "updated_at": row["updated_at"] or "",
    }


def _reader_annotation_from_row(row: sqlite3.Row) -> dict:
    deleted_at = row["deleted_at"] if "deleted_at" in row.keys() else None
    return {
        "id": row["id"],
        "book_id": row["book_id"],
        "chapter_id": row["chapter_id"],
        "chapter_number": row["chapter_number"],
        "chapter_title": row["chapter_title"] or "",
        "kind": row["kind"],
        "paragraph_index": row["paragraph_index"] or 0,
        "char_start": row["char_start"] or 0,
        "char_end": row["char_end"] or 0,
        "selected_text": row["selected_text"] or "",
        "note": row["note"] or "",
        "color": row["color"] or "yellow",
        "client_id": row["client_id"] if "client_id" in row.keys() else "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "deleted_at": deleted_at,
    }


def get_reader_progress(db_path: Path, book_id: int) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                reader_progress.*,
                chapters.chapter_number AS chapter_number,
                chapters.title AS chapter_title
            FROM reader_progress
            JOIN chapters ON chapters.id = reader_progress.chapter_id
            WHERE reader_progress.book_id = ? AND chapters.deleted_at IS NULL
            """,
            (book_id,),
        ).fetchone()
        return _reader_progress_from_row(row)


def upsert_reader_progress(
    db_path: Path,
    *,
    book_id: int,
    chapter_id: int,
    mode: str = "scroll",
    percent: int = 0,
    paragraph_index: int = 0,
    char_offset: int = 0,
    absolute_char_offset: int = 0,
    page_index: int = 0,
    anchor: dict | None = None,
    updated_at: str | None = None,
) -> dict | None:
    updated_at_value = updated_at.strip() if isinstance(updated_at, str) and updated_at.strip() else None
    anchor_json = json.dumps(anchor if isinstance(anchor, dict) else {}, ensure_ascii=False, sort_keys=True)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reader_progress (
                book_id, chapter_id, mode, percent, paragraph_index,
                char_offset, absolute_char_offset, page_index, anchor_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            ON CONFLICT(book_id) DO UPDATE SET
                chapter_id = excluded.chapter_id,
                mode = excluded.mode,
                percent = excluded.percent,
                paragraph_index = excluded.paragraph_index,
                char_offset = excluded.char_offset,
                absolute_char_offset = excluded.absolute_char_offset,
                page_index = excluded.page_index,
                anchor_json = excluded.anchor_json,
                updated_at = excluded.updated_at
            """,
            (
                book_id,
                chapter_id,
                mode,
                percent,
                paragraph_index,
                char_offset,
                absolute_char_offset,
                page_index,
                anchor_json,
                updated_at_value,
            ),
        )
        conn.commit()
    return get_reader_progress(db_path, book_id)


def list_reader_annotations(db_path: Path, book_id: int, include_deleted: bool = False) -> list[dict]:
    deleted_clause = "" if include_deleted else "AND reader_annotations.deleted_at IS NULL"
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                reader_annotations.*,
                chapters.chapter_number AS chapter_number,
                chapters.title AS chapter_title
            FROM reader_annotations
            JOIN chapters ON chapters.id = reader_annotations.chapter_id
            WHERE reader_annotations.book_id = ?
                AND chapters.deleted_at IS NULL
                {deleted_clause}
            ORDER BY chapters.chapter_number ASC,
                     reader_annotations.paragraph_index ASC,
                     reader_annotations.id ASC
            """,
            (book_id,),
        ).fetchall()
        return [_reader_annotation_from_row(row) for row in rows]


def get_reader_annotation(db_path: Path, book_id: int, annotation_id: int, include_deleted: bool = False) -> dict | None:
    deleted_clause = "" if include_deleted else "AND reader_annotations.deleted_at IS NULL"
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT
                reader_annotations.*,
                chapters.chapter_number AS chapter_number,
                chapters.title AS chapter_title
            FROM reader_annotations
            JOIN chapters ON chapters.id = reader_annotations.chapter_id
            WHERE reader_annotations.book_id = ?
                AND reader_annotations.id = ?
                AND chapters.deleted_at IS NULL
                {deleted_clause}
            """,
            (book_id, annotation_id),
        ).fetchone()
        return _reader_annotation_from_row(row) if row else None


def get_reader_annotation_by_client_id(
    db_path: Path,
    book_id: int,
    client_id: str,
    include_deleted: bool = False,
) -> dict | None:
    normalized_client_id = str(client_id or "").strip()
    if not normalized_client_id:
        return None
    deleted_clause = "" if include_deleted else "AND reader_annotations.deleted_at IS NULL"
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT
                reader_annotations.*,
                chapters.chapter_number AS chapter_number,
                chapters.title AS chapter_title
            FROM reader_annotations
            JOIN chapters ON chapters.id = reader_annotations.chapter_id
            WHERE reader_annotations.book_id = ?
                AND reader_annotations.client_id = ?
                AND chapters.deleted_at IS NULL
                {deleted_clause}
            ORDER BY reader_annotations.updated_at DESC,
                     reader_annotations.id DESC
            LIMIT 1
            """,
            (book_id, normalized_client_id),
        ).fetchone()
        return _reader_annotation_from_row(row) if row else None


def add_reader_annotation(
    db_path: Path,
    *,
    book_id: int,
    chapter_id: int,
    kind: str,
    paragraph_index: int = 0,
    char_start: int = 0,
    char_end: int = 0,
    selected_text: str = "",
    note: str = "",
    color: str = "yellow",
    client_id: str = "",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict | None:
    updated_at_value = updated_at.strip() if isinstance(updated_at, str) and updated_at.strip() else None
    created_at_value = created_at.strip() if isinstance(created_at, str) and created_at.strip() else updated_at_value
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO reader_annotations (
                book_id, chapter_id, kind, paragraph_index, char_start,
                char_end, selected_text, note, color, client_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                book_id,
                chapter_id,
                kind,
                paragraph_index,
                char_start,
                char_end,
                selected_text,
                note,
                color,
                str(client_id or "").strip(),
                created_at_value,
                updated_at_value,
            ),
        )
        conn.commit()
        annotation_id = int(cur.lastrowid)
    return get_reader_annotation(db_path, book_id, annotation_id)


def update_reader_annotation(
    db_path: Path,
    *,
    book_id: int,
    annotation_id: int,
    kind: str | None = None,
    paragraph_index: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    selected_text: str | None = None,
    note: str | None = None,
    color: str | None = None,
    client_id: str | None = None,
    updated_at: str | None = None,
) -> dict | None:
    updates = {
        "kind": kind,
        "paragraph_index": paragraph_index,
        "char_start": char_start,
        "char_end": char_end,
        "selected_text": selected_text,
        "note": note,
        "color": color,
        "client_id": client_id.strip() if isinstance(client_id, str) else client_id,
    }
    fields = [f"{column} = ?" for column, value in updates.items() if value is not None]
    params = [value for value in updates.values() if value is not None]
    updated_at_value = updated_at.strip() if isinstance(updated_at, str) and updated_at.strip() else None
    if not fields:
        return get_reader_annotation(db_path, book_id, annotation_id)

    params.extend([updated_at_value, book_id, annotation_id])
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"""
            UPDATE reader_annotations
            SET {', '.join(fields)},
                updated_at = COALESCE(?, CURRENT_TIMESTAMP)
            WHERE book_id = ? AND id = ? AND deleted_at IS NULL
            """,
            params,
        )
        conn.commit()
        if cur.rowcount <= 0:
            return None
    return get_reader_annotation(db_path, book_id, annotation_id)


def soft_delete_reader_annotation(
    db_path: Path,
    book_id: int,
    annotation_id: int,
    *,
    deleted_at: str | None = None,
    updated_at: str | None = None,
) -> bool:
    deleted_at_value = (
        deleted_at.strip()
        if isinstance(deleted_at, str) and deleted_at.strip()
        else datetime.now(timezone.utc).isoformat()
    )
    updated_at_value = updated_at.strip() if isinstance(updated_at, str) and updated_at.strip() else deleted_at_value
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE reader_annotations
            SET deleted_at = ?,
                updated_at = ?
            WHERE book_id = ? AND id = ? AND deleted_at IS NULL
            """,
            (deleted_at_value, updated_at_value, book_id, annotation_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _reader_ai_cache_payload(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    try:
        payload = json.loads(row["response_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    terms = payload.get("terms", [])
    if not isinstance(terms, list):
        terms = []
    normalized_terms = []
    for term in terms:
        if not isinstance(term, dict):
            continue
        normalized_terms.append(
            {
                "source": str(term.get("source") or ""),
                "target": str(term.get("target") or ""),
                "note": str(term.get("note") or ""),
            }
        )

    return {
        "explanation": str(payload.get("explanation") or ""),
        "terms": normalized_terms,
    }


def get_reader_ai_cache(
    db_path: Path,
    *,
    book_id: int,
    chapter_id: int,
    text_hash: str,
    spoiler_mode: str,
) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT response_json
            FROM reader_ai_cache
            WHERE book_id = ?
                AND chapter_id = ?
                AND text_hash = ?
                AND spoiler_mode = ?
            """,
            (book_id, chapter_id, text_hash, spoiler_mode),
        ).fetchone()
    return _reader_ai_cache_payload(row)


def upsert_reader_ai_cache(
    db_path: Path,
    *,
    book_id: int,
    chapter_id: int,
    text_hash: str,
    spoiler_mode: str,
    selected_text: str,
    response: dict,
) -> dict:
    payload = {
        "explanation": str(response.get("explanation") or ""),
        "terms": [
            {
                "source": str(term.get("source") or ""),
                "target": str(term.get("target") or ""),
                "note": str(term.get("note") or ""),
            }
            for term in response.get("terms", [])
            if isinstance(term, dict)
        ],
    }
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reader_ai_cache (
                book_id, chapter_id, text_hash, spoiler_mode, selected_text,
                response_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id, chapter_id, text_hash, spoiler_mode) DO UPDATE SET
                selected_text = excluded.selected_text,
                response_json = excluded.response_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                chapter_id,
                text_hash,
                spoiler_mode,
                selected_text,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    return payload


def _reader_dictionary_cache_payload(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    try:
        payload = json.loads(row["response_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    sources = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        sources.append({str(key): value for key, value in source.items()})

    online = payload.get("online", {})
    if not isinstance(online, dict):
        online = {}

    return {
        "sources": sources,
        "online": {
            "status": str(online.get("status") or row["online_status"] or ""),
            "error": str(online.get("error") or ""),
            "count": int(online.get("count") or len(sources)),
        },
        "updated_at": str(row["updated_at"] or ""),
    }


def get_reader_dictionary_cache(
    db_path: Path,
    *,
    book_id: int,
    query_norm: str,
) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT response_json, online_status, updated_at
            FROM reader_dictionary_cache
            WHERE book_id = ? AND query_norm = ?
            """,
            (book_id, query_norm),
        ).fetchone()
    return _reader_dictionary_cache_payload(row)


def upsert_reader_dictionary_cache(
    db_path: Path,
    *,
    book_id: int,
    query: str,
    query_norm: str,
    response: dict,
) -> dict:
    online = response.get("online", {})
    if not isinstance(online, dict):
        online = {}
    sources = [
        source
        for source in response.get("sources", [])
        if isinstance(source, dict)
    ]
    payload = {
        "sources": sources,
        "online": {
            "status": str(online.get("status") or ""),
            "error": str(online.get("error") or ""),
            "count": int(online.get("count") or len(sources)),
        },
    }
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reader_dictionary_cache (
                book_id, query, query_norm, response_json, source_count,
                online_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id, query_norm) DO UPDATE SET
                query = excluded.query,
                response_json = excluded.response_json,
                source_count = excluded.source_count,
                online_status = excluded.online_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                query,
                query_norm,
                json.dumps(payload, ensure_ascii=False),
                len(sources),
                payload["online"]["status"],
            ),
        )
        conn.commit()
    return payload


# ── Reader X-Ray ──────────────────────────────────────────────────────────────

def _json_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reader_entity_row_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "book_id": row["book_id"],
        "type": row["entity_type"] or "character",
        "name": row["name"] or "",
        "aliases": [str(item) for item in _json_list(row["aliases_json"])],
        "description": row["description"] or "",
        "first_chapter_number": row["first_chapter_number"] or 0,
        "importance": row["importance"] or 0,
        "metadata": _json_object(row["metadata_json"]),
        "mentions": [],
        "mention_count": 0,
    }


def _reader_entity_mention_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "chapter_number": row["chapter_number"] or 0,
        "paragraph_index": row["paragraph_index"] or 0,
        "mention_text": row["mention_text"] or "",
        "context": row["context"] or "",
        "spoiler_level": row["spoiler_level"] or 0,
    }


def _reader_timeline_event_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "chapter_number": row["chapter_number"] or 0,
        "event_order": row["event_order"] or 0,
        "title": row["title"] or "",
        "summary": row["summary"] or "",
        "spoiler_level": row["spoiler_level"] or 0,
        "entities": [str(item) for item in _json_list(row["entities_json"])],
    }


def add_reader_entity(
    db_path: Path,
    *,
    book_id: int,
    entity_type: str,
    name: str,
    aliases: list[str] | None = None,
    description: str = "",
    first_chapter_number: int = 0,
    importance: int = 0,
    metadata: dict | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict:
    with (nullcontext(connection) if connection is not None else get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO reader_entities (
                book_id, entity_type, name, aliases_json, description,
                first_chapter_number, importance, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(book_id, entity_type, name) DO UPDATE SET
                aliases_json = excluded.aliases_json,
                description = excluded.description,
                first_chapter_number = excluded.first_chapter_number,
                importance = excluded.importance,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                entity_type,
                name,
                json.dumps(aliases or [], ensure_ascii=False),
                description,
                first_chapter_number,
                importance,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        row = conn.execute("SELECT id FROM reader_entities WHERE book_id = ? AND entity_type = ? AND name = ?",
                           (book_id, entity_type, name)).fetchone()
        entity_id = int(row["id"])
        if connection is None:
            conn.commit()
        row = conn.execute("SELECT * FROM reader_entities WHERE id = ?", (entity_id,)).fetchone()
    return _reader_entity_row_payload(row)


def add_reader_entity_mention(
    db_path: Path,
    *,
    book_id: int,
    entity_id: int,
    chapter_id: int,
    chapter_number: int,
    paragraph_index: int = 0,
    mention_text: str = "",
    context: str = "",
    spoiler_level: int = 0,
    connection: sqlite3.Connection | None = None,
) -> dict:
    with (nullcontext(connection) if connection is not None else get_connection(db_path)) as conn:
        cur = conn.execute(
            """
            INSERT INTO reader_entity_mentions (
                book_id, entity_id, chapter_id, chapter_number, paragraph_index,
                mention_text, context, spoiler_level
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, entity_id, chapter_id, chapter_number, paragraph_index, mention_text, context, spoiler_level),
        )
        mention_id = int(cur.lastrowid)
        if connection is None:
            conn.commit()
        row = conn.execute("SELECT * FROM reader_entity_mentions WHERE id = ?", (mention_id,)).fetchone()
    return _reader_entity_mention_payload(row)


def add_reader_timeline_event(
    db_path: Path,
    *,
    book_id: int,
    chapter_id: int,
    chapter_number: int,
    title: str,
    summary: str = "",
    event_order: int = 0,
    spoiler_level: int = 0,
    entities: list[str] | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict:
    with (nullcontext(connection) if connection is not None else get_connection(db_path)) as conn:
        cur = conn.execute(
            """
            INSERT INTO reader_timeline_events (
                book_id, chapter_id, chapter_number, event_order, title,
                summary, spoiler_level, entities_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                chapter_id,
                chapter_number,
                event_order,
                title,
                summary,
                spoiler_level,
                json.dumps(entities or [], ensure_ascii=False),
            ),
        )
        event_id = int(cur.lastrowid)
        if connection is None:
            conn.commit()
        row = conn.execute("SELECT * FROM reader_timeline_events WHERE id = ?", (event_id,)).fetchone()
    return _reader_timeline_event_payload(row)


def list_reader_xray_entities(
    db_path: Path,
    book_id: int,
    *,
    max_chapter_number: int | None = None,
) -> list[dict]:
    with get_connection(db_path) as conn:
        if max_chapter_number is None:
            entity_rows = conn.execute(
                """
                SELECT * FROM reader_entities
                WHERE book_id = ?
                ORDER BY importance DESC, first_chapter_number ASC, name ASC
                """,
                (book_id,),
            ).fetchall()
        else:
            entity_rows = conn.execute(
                """
                SELECT DISTINCT reader_entities.*
                FROM reader_entities
                JOIN reader_entity_mentions
                    ON reader_entity_mentions.entity_id = reader_entities.id
                WHERE reader_entities.book_id = ?
                    AND reader_entity_mentions.book_id = reader_entities.book_id
                    AND reader_entity_mentions.chapter_number <= ?
                ORDER BY reader_entities.importance DESC,
                         reader_entities.first_chapter_number ASC,
                         reader_entities.name ASC
                """,
                (book_id, max_chapter_number),
            ).fetchall()

        entities = [_reader_entity_row_payload(row) for row in entity_rows]
        if max_chapter_number is not None:
            for entity in entities:
                entity["aliases"] = []
                entity["description"] = ""
                entity["metadata"] = {}
        if not entities:
            return []

        entity_ids = [entity["id"] for entity in entities]
        placeholders = ", ".join("?" for _ in entity_ids)
        params: list[Any] = [book_id, *entity_ids]
        chapter_clause = ""
        if max_chapter_number is not None:
            chapter_clause = "AND chapter_number <= ?"
            params.append(max_chapter_number)
        mention_rows = conn.execute(
            f"""
            SELECT * FROM reader_entity_mentions
            WHERE book_id = ?
                AND entity_id IN ({placeholders})
                {chapter_clause}
            ORDER BY chapter_number ASC, paragraph_index ASC, id ASC
            """,
            params,
        ).fetchall()

    mentions_by_entity: dict[int, list[dict]] = {}
    for row in mention_rows:
        mentions_by_entity.setdefault(row["entity_id"], []).append(_reader_entity_mention_payload(row))
    for entity in entities:
        entity_mentions = mentions_by_entity.get(entity["id"], [])
        entity["mentions"] = entity_mentions
        entity["mention_count"] = len(entity_mentions)
    return entities


def list_reader_timeline_events(
    db_path: Path,
    book_id: int,
    *,
    max_chapter_number: int | None = None,
) -> list[dict]:
    params: list[Any] = [book_id]
    chapter_clause = ""
    if max_chapter_number is not None:
        chapter_clause = "AND chapter_number <= ?"
        params.append(max_chapter_number)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM reader_timeline_events
            WHERE book_id = ?
                {chapter_clause}
            ORDER BY chapter_number ASC, event_order ASC, id ASC
            """,
            params,
        ).fetchall()
    return [_reader_timeline_event_payload(row) for row in rows]
