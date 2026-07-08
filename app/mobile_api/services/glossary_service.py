from __future__ import annotations

from app.database.db import (
    list_glossary,
    put_glossary_term,
    update_glossary_term,
    approve_glossary_term,
    reject_glossary_term,
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
)
from app.mobile_api.dependencies import get_db_path


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
        put_glossary_term(
            db_path=self.db_path,
            book_id=term_data.get("book_id", 0),
            source=term_data["source_term"],
            target=term_data["target_term"],
            category=term_data.get("category") or term_data.get("term_type", "term"),
            mode=term_data.get("mode", "translate"),
            pinyin=term_data.get("pinyin", ""),
            notes_vi=term_data.get("notes_vi", ""),
            variants=term_data.get("variants", ""),
            approved=term_data.get("approved", 1),
            priority=term_data.get("priority", 0),
            locked=term_data.get("locked", 0),
            genre=term_data.get("genre", ""),
            term_type=term_data.get("term_type") or term_data.get("category", "term"),
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
            term_type=updates.get("term_type"),
        )

    def delete_term(self, term_id: int) -> bool:
        """Delete a glossary term (only if not approved)."""
        # For safety, only allow deletion of pending terms
        from app.database.db import reject_glossary_term  # reject actually deletes if not approved
        return reject_glossary_term(self.db_path, term_id)

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
