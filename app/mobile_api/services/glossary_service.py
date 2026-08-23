from __future__ import annotations

import re
from pathlib import Path

from app.database.db import (
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
    get_chapter_by_id,
    get_connection,
)
from app.database.glossary_repository import (
    GlossaryRepository,
    GlossaryStateConflict,
    GlossaryValidationError,
    normalize_source_key,
)
from app.database.glossary_resolver import resolve_effective_glossary
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
        archived: bool = False,
    ) -> tuple[list[dict], int]:
        """Compatibility wrapper over the SQL review query."""
        result = GlossaryRepository(self.db_path).query(
            book_id=book_id,
            q=search or "",
            mode=mode,
            scope="legacy",
            limit=limit,
            offset=offset,
            approved=approved,
            include_weak=include_weak,
            archived=archived,
        )
        return result["items"], result["total"]

    def query_terms(
        self,
        *,
        book_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        q: str = "",
        review_status: str = "",
        term_type: str | None = None,
        mode: str | None = None,
        locked: bool | None = None,
        scope: str = "all",
        sort: str = "review",
        approved: int | None = None,
        include_weak: bool = False,
        archived: bool = False,
    ) -> dict:
        per_page = min(per_page, 200)
        statuses = tuple(part.strip().upper() for part in review_status.split(",") if part.strip())
        effective_ids = None
        if scope == "effective":
            effective_ids = tuple(
                sorted(
                    {
                        int(term["id"])
                        for term in resolve_effective_glossary(self.db_path, int(book_id or 0)).dictionary_terms
                        if int(term["id"]) > 0
                    }
                )
            )
        result = GlossaryRepository(self.db_path).query(
            book_id=book_id,
            q=q,
            review_statuses=statuses,
            term_type=term_type,
            mode=mode,
            locked=locked,
            scope=scope,
            sort=sort,
            limit=per_page,
            offset=(page - 1) * per_page,
            approved=approved,
            include_weak=include_weak,
            archived=archived,
            effective_ids=effective_ids,
        )
        total = result["total"]
        result.update(
            page=page,
            per_page=per_page,
            pages=(total + per_page - 1) // per_page,
            scope="all" if scope == "legacy" else scope,
        )
        return result

    def search_terms(self, query: str, book_id: int | None = None, limit: int = 20) -> list[dict]:
        """Search glossary terms."""
        terms, _ = self.list_terms(book_id=book_id, limit=1000, search=query)
        return terms[:limit]

    def add_term(self, term_data: dict, *, actor: str = "", request_id: str = "") -> int:
        """Add a new glossary term."""
        term_type = normalize_term_type(term_data.get("term_type") or term_data.get("category", "term"))
        return put_glossary_term(
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
            actor=actor,
            request_id=request_id,
        )

    def add_term_resource(self, term_data: dict, *, actor: str = "", request_id: str = "") -> dict:
        term_id = self.add_term(term_data, actor=actor, request_id=request_id)
        resource = GlossaryRepository(self.db_path).get_resource(term_id)
        if resource is None:
            raise GlossaryStateConflict("term_not_created")
        return resource

    def update_term(
        self,
        term_id: int,
        updates: dict,
        *,
        actor: str = "",
        request_id: str = "",
    ) -> bool:
        """Update a glossary term."""
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
            expected_version=updates.get("expected_version"),
            actor=actor,
            request_id=request_id,
        )

    def update_term_resource(
        self,
        term_id: int,
        updates: dict,
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict | None:
        if not self.update_term(term_id, updates, actor=actor, request_id=request_id):
            return None
        return GlossaryRepository(self.db_path).get_resource(term_id)

    def get_term_detail(self, term_id: int) -> dict | None:
        return GlossaryRepository(self.db_path).get_detail(term_id)

    def bulk_terms(
        self,
        action: str,
        terms: list[dict[str, int]],
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        return GlossaryRepository(self.db_path).bulk(
            action, terms, actor=actor, request_id=request_id
        )

    def delete_term(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        """Archive a glossary term while preserving the existing API contract."""
        return GlossaryRepository(self.db_path).archive(term_id, actor=actor, request_id=request_id)

    def restore_term(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        return GlossaryRepository(self.db_path).restore(term_id, actor=actor, request_id=request_id)

    def approve_term(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        """Approve a pending glossary term."""
        return approve_glossary_term(self.db_path, term_id, actor=actor, request_id=request_id)

    def reject_term(self, term_id: int, *, actor: str = "", request_id: str = "") -> bool:
        """Reject/delete a pending glossary term."""
        return reject_glossary_term(self.db_path, term_id, actor=actor, request_id=request_id)

    def set_term_mode(self, term_id: int, mode: str) -> bool:
        """Set the mode of a glossary term."""
        return set_glossary_term_mode(self.db_path, term_id, mode)

    def set_term_locked(
        self,
        term_id: int,
        locked: bool,
        *,
        actor: str = "",
        request_id: str = "",
    ) -> bool:
        """Lock or unlock a glossary term."""
        return set_glossary_term_locked(
            self.db_path,
            term_id,
            locked,
            actor=actor,
            request_id=request_id,
        )

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

    def query_conflicts(
        self, book_id: int | None = None, page: int = 1, per_page: int = 50
    ) -> dict:
        return GlossaryRepository(self.db_path).query_conflicts(
            book_id=book_id, page=page, per_page=per_page
        )

    def query_legacy_conflicts(
        self,
        book_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
        member_limit: int = 20,
    ) -> list[dict]:
        return GlossaryRepository(self.db_path).query_legacy_conflicts(
            book_id=book_id,
            limit=per_page,
            offset=(page - 1) * per_page,
            member_limit=member_limit,
        )

    def preview_merge(self, canonical_id: int, duplicate_ids: list[int]) -> dict:
        return GlossaryRepository(self.db_path).preview_merge(canonical_id, duplicate_ids)

    def apply_merge(
        self,
        canonical_id: int,
        duplicate_ids: list[int],
        digest: str,
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        return GlossaryRepository(self.db_path).apply_merge(
            canonical_id,
            duplicate_ids,
            digest,
            actor=actor,
            request_id=request_id,
        )

    def extract_chapter_terms(self, book_id: int, chapter_id: int) -> dict:
        """Extract reviewable candidate terms from a chapter's raw Chinese text."""
        chapter = get_chapter_by_id(self.db_path, chapter_id)
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
        for candidate in candidates:
            source = str(candidate["source_term"])
            source_key = normalize_source_key(source)
            with get_connection(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT id, target_term, review_status, approved, locked, archived_at
                    FROM glossary_terms
                    WHERE book_id = ? AND source_key = ?
                    ORDER BY id
                    """,
                    (book_id, source_key),
                ).fetchall()
            if len(rows) > 1 or (
                rows
                and (
                    rows[0]["archived_at"]
                    or (rows[0]["review_status"], rows[0]["approved"], rows[0]["locked"])
                    != ("NEEDS_REVIEW", 0, 0)
                )
            ):
                skipped += 1
                continue
            put_glossary_term(
                self.db_path,
                book_id,
                source,
                str(rows[0]["target_term"] or "") if rows else "",
                category=candidate.get("category") or candidate.get("term_type") or "other",
                confidence=float(candidate.get("confidence") or 0.5),
                approved=0,
                mode="translate",
                term_type=normalize_term_type(candidate.get("term_type")),
                first_seen_chapter_id=chapter_id,
                first_seen_chapter_number=chapter_number,
                review_status="NEEDS_REVIEW",
                source_context=candidate.get("source_context") or "",
                actor="deterministic-extractor",
                request_id=f"chapter:{chapter_id}",
                preserve_existing=True,
            )
            if rows:
                updated += 1
            else:
                created += 1
        return {"created": created, "updated": updated, "skipped": skipped, "candidates": candidates}

    def get_low_coverage_chapters(self, book_id: int, threshold: float = 30.0) -> list[dict]:
        """Get chapters with low glossary coverage."""
        return get_low_coverage_chapters(self.db_path, book_id, threshold)

    def import_glossary(
        self,
        data: list[dict],
        format: str = "json",
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        """Bounded compatibility adapter over the atomic preview/apply flow."""
        repository = GlossaryRepository(self.db_path)
        try:
            preview = repository.preview_import(
                data, "reject_conflicts", legacy_partial=True
            )
            return repository.apply_import(
                data,
                preview["digest"],
                "reject_conflicts",
                actor=actor,
                request_id=request_id,
                legacy_partial=True,
            )
        except GlossaryValidationError as exc:
            return {
                "added": 0,
                "updated": 0,
                "errors": [
                    f"item {error['item']}: "
                    f"{'invalid_transition' if error['code'] == 'invalid_state' else error['code']}"
                    for error in exc.errors
                ],
            }

    def preview_import(
        self,
        data: list[dict],
        conflict_policy: str = "skip_conflicts",
    ) -> dict:
        preview = GlossaryRepository(self.db_path).preview_import(data, conflict_policy)
        return {key: value for key, value in preview.items() if key != "canonical_items"}

    def apply_import(
        self,
        data: list[dict],
        digest: str,
        conflict_policy: str = "skip_conflicts",
        *,
        actor: str = "",
        request_id: str = "",
    ) -> dict:
        return GlossaryRepository(self.db_path).apply_import(
            data,
            digest,
            conflict_policy,
            actor=actor,
            request_id=request_id,
        )

    def export_glossary(
        self,
        book_id: int | None = None,
        scope: str = "all",
    ) -> list[dict]:
        return GlossaryRepository(self.db_path).export_terms(book_id, scope)
