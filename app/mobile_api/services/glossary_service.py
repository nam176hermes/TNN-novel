from __future__ import annotations

import re
from contextlib import nullcontext
from pathlib import Path

from app.database.db import (
    list_glossary,
    put_glossary_term,
    update_glossary_term,
    approve_glossary_term,
    reject_glossary_term,
    delete_glossary_term,
    set_glossary_term_mode,
    set_glossary_term_locked,
    glossary_stats,
    get_glossary_pending,
    add_translation_suggestion,
    get_translation_suggestions,
    delete_translation_suggestion,
    glossary_coverage,
    load_glossary_names,
    auto_approve_glossary,
    get_glossary_conflicts,
    get_low_coverage_chapters,
    add_fuzzy_tm_entry,
    search_fuzzy_tm,
    clear_fuzzy_tm,
    get_chapter_by_id,
    get_connection,
)
from app.mobile_api.dependencies import get_db_path
from app.config import settings
from app.storage.artifact_paths import ArtifactClass, ArtifactPathError, require_artifact_file


PRIORITY_TERM_TYPE_WEIGHTS = {
    "realm": 100,
    "sect": 90,
    "character": 85,
    "place": 85,
    "artifact": 80,
    "technique": 75,
    "concept": 70,
    "title": 65,
}

COMMON_SOURCE_TERMS = {
    "的",
    "了",
    "是",
    "在",
    "有",
    "不",
    "也",
    "都",
    "就",
    "这",
    "那",
    "然后",
    "只是",
    "一个",
    "一下",
    "自己",
}

TERM_TYPE_ALIASES = {
    "CHARACTER": "character",
    "SECT": "sect",
    "REALM": "realm",
    "SKILL": "skill",
    "ARTIFACT": "artifact",
    "LOCATION": "location",
    "TITLE": "title",
    "IDIOM": "idiom",
    "CULTIVATION": "cultivation",
    "ORGANIZATION": "organization",
    "PLACE": "place",
    "OTHER": "other",
}

COMMON_CHINESE_SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢邹喻柏水窦章云苏潘葛范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费薛雷贺倪汤罗毕郝安常乐于傅齐康伍余元顾孟黄穆萧尹"


def normalize_term_type(term_type: str | None) -> str:
    normalized = str(term_type or "other").strip()
    if not normalized:
        return "other"
    return TERM_TYPE_ALIASES.get(normalized.upper(), normalized.lower())


def _context_for(text: str, term: str, radius: int = 28) -> str:
    index = text.find(term)
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + len(term) + radius)
    return text[start:end].replace("\n", " ").strip()


def _normalize_candidate_source(source: str, term_type: str) -> str:
    source = source.strip("，。！？、：；（）()[]【】《》“”\"' \n\t")
    for marker in ("来到", "进入", "取出", "拿出", "走入", "回到", "前往", "拜入"):
        if marker in source:
            source = source.split(marker)[-1]
    source = re.sub(r"^(?:随后|然后|只见|便见|来到|进入|取出|拿出|到|入|进|出|去|往)", "", source)
    if term_type == "character" and source.endswith(("宗", "门", "派", "阁", "宫", "殿", "境", "期", "丹", "剑", "符")):
        return ""
    return source


def extract_candidate_terms_from_text(text: str) -> list[dict]:
    """Lightweight Chinese webnovel term extraction.

    It is intentionally conservative and review-first: candidates are never
    auto-approved and are safe to run after import or translation jobs.
    """
    text = text or ""
    patterns: list[tuple[str, str]] = [
        (rf"[{COMMON_CHINESE_SURNAMES}][\u4e00-\u9fff]{{1,2}}", "character"),
        (r"[\u4e00-\u9fff]{2,8}(?:宗|门|派|阁|宫|殿|教|族)", "sect"),
        (r"[\u4e00-\u9fff]{1,6}(?:境|期|层|阶)", "realm"),
        (r"[\u4e00-\u9fff]{1,8}(?:功|法|术|诀|剑诀|神通)", "skill"),
        (r"[\u4e00-\u9fff]{1,8}(?:丹|剑|珠|符|炉|鼎|印|幡)", "artifact"),
        (r"[\u4e00-\u9fff]{2,8}(?:山|城|谷|峰|岛|洲|界|域)", "place"),
    ]
    seen: set[str] = set()
    candidates: list[dict] = []
    for pattern, term_type in patterns:
        for match in re.finditer(pattern, text):
            source = _normalize_candidate_source(match.group(0), term_type)
            if len(source) < 2 or source in COMMON_SOURCE_TERMS or source in seen:
                continue
            seen.add(source)
            candidates.append(
                {
                    "source_term": source,
                    "target_term": "",
                    "term_type": term_type,
                    "category": term_type,
                    "confidence": 0.55 if term_type == "character" else 0.65,
                    "source_context": _context_for(text, source),
                }
            )
    return candidates


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _is_weak_term(term: dict) -> bool:
    source = str(term.get("source_term") or "").strip()
    target = str(term.get("target_term") or "").strip()
    if not source or not target:
        return True
    if len(source) <= 1:
        return True
    if source in COMMON_SOURCE_TERMS:
        return True
    return False


def _review_priority_score(term: dict) -> int:
    term_type = str(term.get("term_type") or term.get("category") or "term")
    occurrence_count = _as_int(term.get("occurrence_count"))
    priority = _as_int(term.get("priority"))
    locked = _as_int(term.get("locked"))
    approved = _as_int(term.get("approved"), 1)
    repeated_score = min(occurrence_count, 10) * 6 if occurrence_count >= 2 else 0
    return (
        (0 if approved == 0 else -10)
        + (locked * 20)
        + priority
        + PRIORITY_TERM_TYPE_WEIGHTS.get(term_type, 0)
        + repeated_score
    )


def _sort_glossary_for_review(terms: list[dict]) -> list[dict]:
    return sorted(
        terms,
        key=lambda term: (
            -_review_priority_score(term),
            -_as_int(term.get("occurrence_count")),
            -len(str(term.get("source_term") or "")),
            str(term.get("source_term") or ""),
        ),
    )


class GlossaryService:
    def __init__(self):
        self.db_path = get_db_path()

    @classmethod
    def from_db_path(cls, db_path) -> "GlossaryService":
        service = object.__new__(cls)
        service.db_path = Path(db_path)
        return service

    def list_terms(
        self,
        book_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        mode: str | None = None,
        approved: int | None = None,
        include_weak: bool = False,
    ) -> tuple[list[dict], int]:
        """List glossary terms with pagination and filtering."""
        # For simplicity, we'll load all and filter (in production, add SQL WHERE clauses)
        all_terms = list_glossary(self.db_path, book_id)

        # Apply filters
        filtered = all_terms
        if search:
            search_lower = search.lower()
            filtered = [
                t for t in filtered
                if search_lower in t["source_term"].lower()
                or search_lower in t["target_term"].lower()
            ]
        if mode is not None:
            filtered = [t for t in filtered if t.get("mode") == mode]
        if approved is not None:
            filtered = [t for t in filtered if t.get("approved") == approved]
        if not include_weak:
            filtered = [t for t in filtered if not _is_weak_term(t)]
        filtered = _sort_glossary_for_review(filtered)

        total = len(filtered)
        # Apply pagination
        paginated = filtered[offset:offset + limit]
        return paginated, total

    def search_terms(self, query: str, book_id: int | None = None, limit: int = 20) -> list[dict]:
        """Search glossary terms."""
        terms, _ = self.list_terms(book_id=book_id, limit=1000, search=query)
        return terms[:limit]

    def add_term(self, term_data: dict) -> int:
        """Add a new glossary term."""
        term_type = normalize_term_type(term_data.get("term_type") or term_data.get("category", "term"))
        put_glossary_term(
            db_path=self.db_path,
            book_id=term_data.get("book_id", 0),
            source=term_data["source_term"],
            target=term_data["target_term"],
            category=term_data.get("category") or term_type,
            mode=term_data.get("mode", "translate"),
            pinyin=term_data.get("pinyin", ""),
            notes_vi=term_data.get("notes_vi", ""),
            variants=term_data.get("variants", ""),
            approved=term_data.get("approved", 1),
            priority=term_data.get("priority", 0),
            locked=term_data.get("locked", 0),
            genre=term_data.get("genre", ""),
            term_type=term_type,
            alternatives=term_data.get("alternatives", ""),
            gender=term_data.get("gender", ""),
            first_seen_chapter_id=term_data.get("first_seen_chapter_id", 0),
            first_seen_chapter_number=term_data.get("first_seen_chapter_number", 0),
            review_status=term_data.get("review_status", ""),
            source_context=term_data.get("source_context", ""),
        )
        # Return the ID of the inserted/updated term (simplified)
        terms = list_glossary(self.db_path, term_data.get("book_id", 0))
        for t in reversed(terms):  # Get most recent
            if t["source_term"] == term_data["source_term"] and t["target_term"] == term_data["target_term"]:
                return t["id"]
        return 0

    def update_term(self, term_id: int, updates: dict) -> bool:
        """Update a glossary term."""
        # Get current term
        terms = list_glossary(self.db_path)
        current = None
        for t in terms:
            if t["id"] == term_id:
                current = t
                break
        if not current:
            return False

        return update_glossary_term(
            db_path=self.db_path,
            term_id=term_id,
            target_term=updates.get("target_term"),
            category=updates.get("category"),
            mode=updates.get("mode"),
            pinyin=updates.get("pinyin"),
            notes_vi=updates.get("notes_vi"),
            variants=updates.get("variants"),
            approved=updates.get("approved"),
            priority=updates.get("priority"),
            locked=updates.get("locked"),
            genre=updates.get("genre"),
            term_type=normalize_term_type(updates.get("term_type")) if updates.get("term_type") is not None else None,
            alternatives=updates.get("alternatives"),
            gender=updates.get("gender"),
            review_status=updates.get("review_status"),
            source_context=updates.get("source_context"),
        )

    def delete_term(self, term_id: int) -> bool:
        """Hard-delete a glossary term for explicit destructive actions."""
        return delete_glossary_term(self.db_path, term_id)

    def approve_term(self, term_id: int) -> bool:
        """Approve a pending glossary term."""
        return approve_glossary_term(self.db_path, term_id)

    def reject_term(self, term_id: int) -> bool:
        """Reject/delete a pending glossary term."""
        return reject_glossary_term(self.db_path, term_id)

    def set_term_mode(self, term_id: int, mode: str) -> bool:
        """Set the mode of a glossary term."""
        return set_glossary_term_mode(self.db_path, term_id, mode)

    def set_term_locked(self, term_id: int, locked: bool) -> bool:
        """Lock or unlock a glossary term."""
        return set_glossary_term_locked(self.db_path, term_id, locked)

    def get_stats(self, book_id: int | None = None) -> dict:
        """Get glossary statistics."""
        return glossary_stats(self.db_path, book_id)

    def get_pending(self, book_id: int | None = None, limit: int = 20) -> list[dict]:
        """Get pending glossary terms."""
        return get_glossary_pending(self.db_path, book_id, limit)

    def add_suggestion(self, source: str, target: str, book_id: int | None = None, chapter_number: int | None = None) -> None:
        """Add a translation suggestion."""
        add_translation_suggestion(
            db_path=self.db_path,
            q=source,
            s=target,
            source_lang="zh",
            target_lang="vi",
            book_id=book_id,
            chapter_number=chapter_number,
        )

    def get_suggestions(self, limit: int = 50, book_id: int | None = None) -> list[dict]:
        """Get translation suggestions."""
        return get_translation_suggestions(self.db_path, limit, book_id)

    def delete_suggestion(self, suggestion_id: int) -> bool:
        """Delete a translation suggestion."""
        return delete_translation_suggestion(self.db_path, suggestion_id)

    def add_tm_entry(
        self,
        source_text: str,
        translation_text: str,
        score: int = 85,
        book_id: int = 0,
        chapter_number: int | None = None,
        source_lang: str = "zh",
        target_lang: str = "vi",
    ) -> int:
        """Add or update a fuzzy translation memory entry."""
        return add_fuzzy_tm_entry(
            self.db_path,
            source_text,
            translation_text,
            score=score,
            book_id=book_id,
            chapter_number=chapter_number,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def search_tm(
        self,
        source_text: str,
        threshold: int = 80,
        limit: int = 10,
        book_id: int | None = None,
        source_lang: str = "zh",
        target_lang: str = "vi",
    ) -> list[dict]:
        """Search fuzzy translation memory entries."""
        return search_fuzzy_tm(
            self.db_path,
            source_text,
            threshold=threshold,
            limit=limit,
            book_id=book_id,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def clear_tm(self) -> int:
        """Delete all fuzzy translation memory entries."""
        return clear_fuzzy_tm(self.db_path)

    def get_coverage(self, book_id: int, source_text: str) -> dict:
        """Get glossary coverage for text."""
        return glossary_coverage(self.db_path, book_id, source_text)

    def get_name_map(self, book_id: int = 0) -> dict[str, str]:
        """Get name map (transliteration terms)."""
        return load_glossary_names(self.db_path, book_id)

    def auto_approve(self, min_occurrences: int = 3, book_id: int | None = None) -> int:
        """Auto-approve terms with sufficient occurrences."""
        return auto_approve_glossary(self.db_path, min_occurrences, book_id)

    def get_conflicts(self, book_id: int | None = None) -> list[dict]:
        """Get glossary conflicts."""
        return get_glossary_conflicts(self.db_path, book_id)

    def extract_chapter_terms(self, book_id: int, chapter_id: int, *, connection=None, chapter=None) -> dict:
        """Extract reviewable candidate terms from a chapter's raw Chinese text."""
        chapter = chapter if chapter is not None else get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or int(chapter.get("book_id") or 0) != int(book_id):
            raise ValueError("Chapter not found")
        raw_path = str(chapter.get("raw_text_path") or "").strip()
        raw_text = ""
        if raw_path:
            try:
                resolved_raw_path = require_artifact_file(
                    raw_path,
                    artifact_class=ArtifactClass.RAW,
                    data_root=self.db_path.parent,
                    old_root=settings.artifact_legacy_root,
                )
            except ArtifactPathError:
                resolved_raw_path = None
            if resolved_raw_path is not None:
                raw_text = resolved_raw_path.read_text(encoding="utf-8", errors="replace")
        if not raw_text:
            return {"created": 0, "updated": 0, "skipped": 0, "candidates": []}

        candidates = extract_candidate_terms_from_text(raw_text)
        created = 0
        updated = 0
        skipped = 0
        chapter_number = int(chapter.get("chapter_number") or 0)
        with (nullcontext(connection) if connection is not None else get_connection(self.db_path)) as conn:
            for candidate in candidates:
                source = str(candidate["source_term"])
                existing = conn.execute(
                    "SELECT id, review_status FROM glossary_terms WHERE book_id = ? AND source_term = ?",
                    (book_id, source),
                ).fetchone()
                if existing and str(existing["review_status"] or "").upper() in {"APPROVED", "LOCKED", "REJECTED"}:
                    skipped += 1
                    continue
                if existing:
                    conn.execute(
                        """
                        UPDATE glossary_terms
                        SET occurrence_count = occurrence_count + 1,
                            last_seen = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            source_context = COALESCE(NULLIF(?, ''), source_context),
                            review_status = CASE
                                WHEN review_status IS NULL OR review_status = '' THEN 'NEEDS_REVIEW'
                                ELSE review_status
                            END
                        WHERE id = ?
                        """,
                        (candidate.get("source_context") or "", existing["id"]),
                    )
                    updated += 1
                    continue
                conn.execute(
                    """
                    INSERT INTO glossary_terms
                    (book_id, source_term, target_term, category, confidence, approved, mode,
                     term_type, first_seen_chapter_id, first_seen_chapter_number,
                     review_status, source_context, occurrence_count, last_seen, updated_at)
                    VALUES (?, ?, '', ?, ?, 0, 'translate', ?, ?, ?, 'NEEDS_REVIEW', ?, 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        book_id,
                        source,
                        candidate.get("category") or candidate.get("term_type") or "other",
                        float(candidate.get("confidence") or 0.5),
                        normalize_term_type(candidate.get("term_type")),
                        chapter_id,
                        chapter_number,
                        candidate.get("source_context") or "",
                    ),
                )
                created += 1
            if connection is None:
                conn.commit()
        return {"created": created, "updated": updated, "skipped": skipped, "candidates": candidates}

    def get_low_coverage_chapters(self, book_id: int, threshold: float = 30.0) -> list[dict]:
        """Get chapters with low glossary coverage."""
        return get_low_coverage_chapters(self.db_path, book_id, threshold)

    def import_glossary(self, data: list[dict], format: str = "json") -> dict:
        """Import glossary from JSON or CSV."""
        added = 0
        updated = 0
        errors = []

        for item in data:
            try:
                # Validate required fields
                if "source_term" not in item or "target_term" not in item:
                    errors.append(f"Missing source_term or target_term in item: {item}")
                    continue

                # Check if term exists
                existing = None
                terms = list_glossary(self.db_path, item.get("book_id", 0))
                for t in terms:
                    if t["source_term"] == item["source_term"] and t["book_id"] == item.get("book_id", 0):
                        existing = t
                        break

                if existing:
                    # Update existing
                    self.update_term(existing["id"], {
                        "target_term": item.get("target_term", existing["target_term"]),
                        "category": item.get("category", existing.get("category", "term")),
                        "mode": item.get("mode", existing.get("mode", "translate")),
                        "pinyin": item.get("pinyin", existing.get("pinyin", "")),
                        "notes_vi": item.get("notes_vi", existing.get("notes_vi", "")),
                        "variants": item.get("variants", existing.get("variants", "")),
                        # Keep existing approved status unless explicitly set
                        "approved": item.get("approved", existing.get("approved", 1)),
                    })
                    updated += 1
                else:
                    # Add new
                    self.add_term(item)
                    added += 1

            except Exception as exc:
                errors.append(f"Failed to process item {item}: {exc}")

        return {"added": added, "updated": updated, "errors": errors}

    def export_glossary(self, book_id: int | None = None, format: str = "json") -> list[dict]:
        """Export glossary as JSON or CSV."""
        terms, _ = self.list_terms(book_id=book_id, limit=10000)  # Get all
        return terms
