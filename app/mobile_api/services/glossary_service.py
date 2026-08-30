from __future__ import annotations

from collections import Counter
import json
import os
import re
import unicodedata
from pathlib import Path

import requests

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
    get_book_by_id,
    get_connection,
    list_model_providers,
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
from app.translation.ollama_client import call_openai_compatible_chat


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
    "什么",
    "怎么",
    "他们",
    "我们",
    "你们",
}

COMMON_TERM_BOUNDARIES = set("的了是在有不也都就这那其而与及又将把被着过")
DETERMINISTIC_EXTRACTOR = "deterministic-v2"
HYBRID_EXTRACTOR = "hybrid-v1"
MAX_HYBRID_TEXT_CHARS = 12_000
MAX_HYBRID_CANDIDATES = 100
HYBRID_WARNING_MESSAGE = "Hybrid glossary extraction was skipped."
VALID_EXTRACTED_TERM_TYPES = {
    "artifact", "character", "concept", "cultivation", "idiom", "location", "organization",
    "other", "place", "realm", "sect", "skill", "technique", "term", "title",
}
SUFFIX_TERM_TYPES = {
    "剑诀": "skill",
    "神通": "skill",
    "道君": "title",
    "真人": "title",
    "宗": "sect",
    "门": "sect",
    "派": "sect",
    "阁": "sect",
    "宫": "sect",
    "殿": "sect",
    "教": "sect",
    "族": "sect",
    "境": "realm",
    "期": "realm",
    "层": "realm",
    "阶": "realm",
    "功": "skill",
    "法": "skill",
    "术": "skill",
    "诀": "skill",
    "典": "skill",
    "丹": "artifact",
    "剑": "artifact",
    "珠": "artifact",
    "符": "artifact",
    "炉": "artifact",
    "鼎": "artifact",
    "印": "artifact",
    "幡": "artifact",
    "山": "place",
    "城": "place",
    "谷": "place",
    "峰": "place",
    "岛": "place",
    "洲": "place",
    "界": "place",
    "域": "place",
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


def _cluster_end(text: str, start: int) -> int:
    end = start + 1
    while end < len(text) and unicodedata.combining(text[end]):
        end += 1
    return end


def _is_hangul_leading_jamo(value: str) -> bool:
    return len(value) == 1 and 0x1100 <= ord(value) <= 0x1112


def _is_hangul_vowel_cluster(value: str) -> bool:
    return bool(value) and 0x1161 <= ord(value[0]) <= 0x1175 and all(
        unicodedata.combining(character) for character in value[1:]
    )


def _is_hangul_trailing_cluster(value: str) -> bool:
    return bool(value) and 0x11A8 <= ord(value[0]) <= 0x11C2 and all(
        unicodedata.combining(character) for character in value[1:]
    )


def _is_hangul_lv_syllable(value: str) -> bool:
    return len(value) == 1 and 0xAC00 <= ord(value) <= 0xD7A3 and (
        ord(value) - 0xAC00
    ) % 28 == 0


def _normalized_with_original_spans(text: str) -> tuple[str, list[tuple[int, int]]]:
    normalized_parts: list[str] = []
    original_spans: list[tuple[int, int]] = []
    cluster_start = 0
    while cluster_start < len(text):
        cluster_end = _cluster_end(text, cluster_start)
        normalized_cluster = unicodedata.normalize("NFKC", text[cluster_start:cluster_end])
        if _is_hangul_leading_jamo(normalized_cluster) and cluster_end < len(text):
            vowel_end = _cluster_end(text, cluster_end)
            normalized_vowel = unicodedata.normalize("NFKC", text[cluster_end:vowel_end])
            if _is_hangul_vowel_cluster(normalized_vowel):
                cluster_end = vowel_end
                normalized_cluster = unicodedata.normalize(
                    "NFKC", text[cluster_start:cluster_end]
                )
                if _is_hangul_lv_syllable(normalized_cluster) and cluster_end < len(text):
                    trailing_end = _cluster_end(text, cluster_end)
                    normalized_trailing = unicodedata.normalize(
                        "NFKC", text[cluster_end:trailing_end]
                    )
                    if _is_hangul_trailing_cluster(normalized_trailing):
                        cluster_end = trailing_end
                        normalized_cluster = unicodedata.normalize(
                            "NFKC", text[cluster_start:cluster_end]
                        )
        normalized_parts.append(normalized_cluster)
        original_spans.extend([(cluster_start, cluster_end)] * len(normalized_cluster))
        cluster_start = cluster_end
    return "".join(normalized_parts), original_spans


def _context_for_normalized(text: str, normalized_term: str, radius: int = 28) -> str:
    normalized_text, original_spans = _normalized_with_original_spans(text)
    normalized_index = normalized_text.find(normalized_term)
    if normalized_index < 0 or not normalized_term:
        return ""
    original_start = original_spans[normalized_index][0]
    original_end = original_spans[normalized_index + len(normalized_term) - 1][1]
    return text[
        max(0, original_start - radius):min(len(text), original_end + radius)
    ].replace("\n", " ").strip()


def _normalized_extraction_corpus(title: str, text: str) -> tuple[str, str]:
    normalized_title = unicodedata.normalize("NFKC", title)
    normalized_text = unicodedata.normalize("NFKC", text)
    return normalized_title, f"{normalized_title}\n{normalized_text}"


def _normalize_candidate_source(source: str, term_type: str) -> str:
    source = source.strip("，。！？、：；（）()[]【】《》“”\"' \n\t")
    for marker in ("来到", "进入", "取出", "拿出", "走入", "回到", "前往", "拜入"):
        if marker in source:
            source = source.split(marker)[-1]
    source = re.sub(r"^(?:随后|然后|只见|便见|来到|进入|取出|拿出|到|入|进|出|去|往)", "", source)
    if term_type == "character" and source.endswith(("宗", "门", "派", "阁", "宫", "殿", "境", "期", "丹", "剑", "符")):
        return ""
    return source


def _candidate_term_type(source: str, fallback: str = "term") -> str:
    for suffix, term_type in SUFFIX_TERM_TYPES.items():
        if source.endswith(suffix):
            return term_type
    return fallback


def _valid_candidate_source(source: str) -> bool:
    return (
        2 <= len(source) <= 32
        and source not in COMMON_SOURCE_TERMS
        and source[0] not in COMMON_TERM_BOUNDARIES
        and source[-1] not in COMMON_TERM_BOUNDARIES
        and bool(re.fullmatch(r"[\u3400-\u9fff]+", source))
    )


def _clean_chapter_title(title: str) -> str:
    return re.sub(
        r"^\s*第[〇零一二三四五六七八九十百千万两\d]+章\s*[:：\-—]?\s*",
        "",
        str(title or ""),
    ).strip()


def extract_candidate_terms_from_text(text: str, chapter_title: str = "") -> list[dict]:
    """Lightweight Chinese webnovel term extraction.

    It is intentionally conservative and review-first: candidates are never
    auto-approved and are safe to run after import or translation jobs.
    """
    text = text or ""
    title = _clean_chapter_title(chapter_title)
    normalized_title, normalized_corpus = _normalized_extraction_corpus(title, text)
    patterns: list[tuple[str, str] | tuple[str, str, str]] = [
        (rf"[{COMMON_CHINESE_SURNAMES}][\u4e00-\u9fff]{{1,2}}", "character"),
        (r"[\u4e00-\u9fff]{1,8}(?:宗|门|派|阁|宫|殿|教|族)", "sect", "suffix"),
        (r"[\u4e00-\u9fff]{1,6}(?:境|期|层|阶)", "realm", "suffix"),
        (r"[\u4e00-\u9fff]{1,8}(?:剑诀|神通|功|法|术|诀|典)", "skill", "suffix"),
        (r"[\u4e00-\u9fff]{1,8}(?:丹|剑|珠|符|炉|鼎|印|幡)", "artifact", "suffix"),
        (r"[\u4e00-\u9fff]{1,8}(?:山|城|谷|峰|岛|洲|界|域)", "place", "suffix"),
        (r"[\u4e00-\u9fff]{1,8}(?:道君|真人)", "title", "suffix"),
    ]
    by_source: dict[str, dict] = {}

    def observe(source: str, term_type: str, evidence_type: str, confidence: float) -> None:
        source = unicodedata.normalize(
            "NFKC", _normalize_candidate_source(source, term_type)
        )
        if not _valid_candidate_source(source):
            return
        item = by_source.get(source)
        if item is None:
            item = {
                "source_term": source,
                "target_term": "",
                "term_type": term_type,
                "category": term_type,
                "confidence": confidence,
                "source_context": _context_for_normalized(text, source),
                "mention_count": 0,
                "title_match": bool(normalized_title and source in normalized_title),
                "evidence_types": [evidence_type],
            }
            by_source[source] = item
            return
        item["confidence"] = max(float(item["confidence"]), confidence)
        item["title_match"] = bool(
            item["title_match"] or (normalized_title and source in normalized_title)
        )
        if evidence_type not in item["evidence_types"]:
            item["evidence_types"].append(evidence_type)

    for pattern, term_type, *evidence in patterns:
        for match in re.finditer(pattern, text):
            observe(
                match.group(0),
                term_type,
                evidence[0] if evidence else "name_pattern",
                0.55 if term_type == "character" else 0.65,
            )

    for source in re.findall(r"[\u3400-\u9fff]{2,32}", title):
        observe(source, _candidate_term_type(source, "title"), "chapter_title", 0.75)

    ngram_counts: Counter[str] = Counter()
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        for size in range(2, min(6, len(run)) + 1):
            ngram_counts.update(run[index:index + size] for index in range(len(run) - size + 1))
    repeated = [
        (source, count)
        for source, count in ngram_counts.items()
        if count >= 2 and _valid_candidate_source(source)
    ]
    maximal: list[tuple[str, int]] = []
    for source, count in sorted(repeated, key=lambda item: (-len(item[0]), -item[1], item[0])):
        if any(source in longer and longer_count >= count for longer, longer_count in maximal):
            continue
        maximal.append((source, count))
        observe(source, _candidate_term_type(source), "repeated_ngram", min(0.8, 0.5 + count * 0.05))

    for source, item in by_source.items():
        item["mention_count"] = sum(
            1 for _ in re.finditer(f"(?={re.escape(source)})", normalized_corpus)
        )

    return sorted(
        by_source.values(),
        key=lambda item: (
            -int(bool(item["title_match"])),
            -int(item["mention_count"]),
            -len(str(item["source_term"])),
            str(item["source_term"]),
        ),
    )


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

    def get_extraction_settings(self, book_id: int) -> dict:
        if get_book_by_id(self.db_path, book_id) is None:
            raise ValueError("book_not_found")
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT extraction_mode, provider_id FROM book_glossary_settings WHERE book_id = ?",
                (book_id,),
            ).fetchone()
        return {
            "book_id": book_id,
            "mode": str(row["extraction_mode"]) if row else "deterministic",
            "provider_id": str(row["provider_id"] or "") if row else "",
            "max_candidates_per_chapter": MAX_HYBRID_CANDIDATES,
        }

    def update_extraction_settings(self, book_id: int, *, mode: str, provider_id: str = "") -> dict:
        if get_book_by_id(self.db_path, book_id) is None:
            raise ValueError("book_not_found")
        if mode not in {"deterministic", "hybrid"}:
            raise ValueError("invalid_extraction_mode")
        resolved_provider_id = str(provider_id or "").strip() if mode == "hybrid" else ""
        if mode == "hybrid":
            provider = next(
                (item for item in list_model_providers(self.db_path) if item["id"] == resolved_provider_id),
                None,
            )
            if (
                provider is None
                or int(provider.get("enabled") or 0) != 1
                or not str(provider.get("base_url") or "").strip()
                or not str(provider.get("model") or "").strip()
                or (
                    bool(str(provider.get("api_key_env") or "").strip())
                    and not bool(provider.get("api_key_set"))
                )
            ):
                raise ValueError("provider_not_configured")
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO book_glossary_settings (book_id, extraction_mode, provider_id, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(book_id) DO UPDATE SET
                    extraction_mode = excluded.extraction_mode,
                    provider_id = excluded.provider_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (book_id, mode, resolved_provider_id),
            )
            conn.commit()
        return self.get_extraction_settings(book_id)

    def _hybrid_candidates(
        self,
        *,
        book_id: int,
        chapter_id: int,
        chapter_title: str,
        raw_text: str,
        provider_id: str,
    ) -> tuple[list[dict] | None, list[dict], str]:
        warnings: list[dict] = []
        provider = next(
            (item for item in list_model_providers(self.db_path) if item["id"] == provider_id),
            None,
        )
        if provider is None or int(provider.get("enabled") or 0) != 1:
            return None, [{"code": "provider_not_configured", "message": HYBRID_WARNING_MESSAGE}], ""
        api_key_env = str(provider.get("api_key_env") or "").strip()
        api_key = os.environ.get(api_key_env, "").strip() if api_key_env else ""
        if api_key_env and not api_key:
            return None, [{"code": "provider_not_configured", "message": HYBRID_WARNING_MESSAGE}], ""

        bounded_title = _clean_chapter_title(chapter_title)[:200]
        bounded_text = raw_text[:MAX_HYBRID_TEXT_CHARS]
        prompt = (
            "Extract glossary candidates from this Chinese web-novel chapter. "
            "Return one JSON object with a candidates array. Each item may contain only "
            "source_term, target_term, term_type, and confidence. Do not return more than 100 items. "
            "Candidates are review suggestions, never approvals.\n"
            f"TITLE:\n{bounded_title}\nCHAPTER:\n{bounded_text}"
        )
        try:
            response = call_openai_compatible_chat(
                prompt=prompt,
                base_url=str(provider["base_url"]),
                model=str(provider["model"]),
                api_key=api_key,
                temperature=0.0,
                timeout=min(60, max(1, int(provider.get("timeout_seconds") or 60))),
                max_retries=0,
                response_format={"type": "json_object"},
            )
        except requests.RequestException:
            return None, [{"code": "provider_unavailable", "message": HYBRID_WARNING_MESSAGE}], ""

        try:
            payload = json.loads(str(response.get("text") or ""))
            raw_candidates = payload["candidates"]
            if not isinstance(payload, dict) or not isinstance(raw_candidates, list):
                raise ValueError("invalid_candidates")
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, [{"code": "provider_malformed_response", "message": HYBRID_WARNING_MESSAGE}], ""

        if len(raw_candidates) > MAX_HYBRID_CANDIDATES:
            raw_candidates = raw_candidates[:MAX_HYBRID_CANDIDATES]
            warnings.append(
                {"code": "provider_output_truncated", "message": "Hybrid output was limited to 100 candidates."}
            )
        normalized_title, normalized_corpus = _normalized_extraction_corpus(
            bounded_title, bounded_text
        )
        candidates: list[dict] = []
        seen: set[str] = set()
        invalid_count = duplicate_count = 0
        for item in raw_candidates:
            if not isinstance(item, dict) or not isinstance(item.get("source_term"), str):
                invalid_count += 1
                continue
            source = " ".join(
                unicodedata.normalize("NFKC", str(item["source_term"])).split()
            )
            source_key = normalize_source_key(source)
            target_value = item.get("target_term", "")
            confidence_value = item.get("confidence", 0.5)
            if (
                not source_key
                or len(source) > 64
                or source not in normalized_corpus
                or not isinstance(target_value, str)
                or len(target_value) > 200
                or isinstance(confidence_value, bool)
                or not isinstance(confidence_value, int | float)
                or not 0 <= float(confidence_value) <= 1
            ):
                invalid_count += 1
                continue
            if source_key in seen:
                duplicate_count += 1
                continue
            seen.add(source_key)
            term_type = normalize_term_type(str(item.get("term_type") or "other"))
            if term_type not in VALID_EXTRACTED_TERM_TYPES:
                term_type = "other"
            candidates.append(
                {
                    "source_term": source,
                    "target_term": target_value.strip(),
                    "term_type": term_type,
                    "category": term_type,
                    "confidence": float(confidence_value),
                    "source_context": _context_for_normalized(bounded_text, source),
                    "mention_count": sum(
                        1
                        for _ in re.finditer(
                            f"(?={re.escape(source)})", normalized_corpus
                        )
                    ),
                    "title_match": bool(normalized_title and source in normalized_title),
                    "evidence_types": ["provider_structured_json"],
                }
            )
        if duplicate_count:
            warnings.append(
                {"code": "provider_duplicates_ignored", "message": "Duplicate hybrid candidates were ignored."}
            )
        if invalid_count:
            warnings.append(
                {"code": "provider_items_ignored", "message": "Invalid hybrid candidates were ignored."}
            )

        effective_keys = set(resolve_effective_glossary(self.db_path, book_id).reserved_source_keys)
        with get_connection(self.db_path) as conn:
            reviewed_keys = {
                str(row["source_key"])
                for row in conn.execute(
                    "SELECT source_key FROM glossary_terms WHERE book_id = ? "
                    "AND review_status IN ('APPROVED', 'LOCKED', 'REJECTED') "
                    "AND COALESCE(archived_at, '') = ''",
                    (book_id,),
                ).fetchall()
            }
            evidenced_keys = {
                str(row["source_key"])
                for row in conn.execute(
                    """
                    SELECT DISTINCT g.source_key
                    FROM glossary_term_evidence e
                    JOIN glossary_terms g ON g.id = e.term_id
                    WHERE g.book_id = ? AND e.chapter_id = ?
                      AND e.extractor != ?
                    """,
                    (book_id, chapter_id, HYBRID_EXTRACTOR),
                ).fetchall()
            }
        retained: list[dict] = []
        for candidate in candidates:
            source_key = normalize_source_key(candidate["source_term"])
            if source_key in effective_keys | reviewed_keys:
                retained.append({**candidate, "observe_only": True})
            elif source_key not in evidenced_keys:
                retained.append(candidate)
        return retained, warnings, normalized_corpus

    def extract_chapter_terms(self, book_id: int, chapter_id: int) -> dict:
        """Extract reviewable candidate terms from a chapter's raw Chinese text."""
        chapter = get_chapter_by_id(self.db_path, chapter_id)
        if not chapter or int(chapter.get("book_id") or 0) != int(book_id):
            raise ValueError("Chapter not found")
        raw_path = str(chapter.get("raw_text_path") or "").strip()
        raw_text = ""
        resolved_raw_path: Path | None = None
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
        if resolved_raw_path is None:
            return {"created": 0, "updated": 0, "skipped": 0, "candidates": [], "warnings": []}
        if not raw_text:
            chapter_number = int(chapter.get("chapter_number") or 0)
            repository = GlossaryRepository(self.db_path)
            counts = repository.record_extraction_candidates(
                book_id=book_id,
                chapter_id=chapter_id,
                chapter_number=chapter_number,
                extractor=DETERMINISTIC_EXTRACTOR,
                candidates=[],
                occurrence_corpus="",
            )
            if self.get_extraction_settings(book_id)["mode"] == "hybrid":
                hybrid_counts = repository.record_extraction_candidates(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                    extractor=HYBRID_EXTRACTOR,
                    candidates=[],
                    occurrence_corpus="",
                )
                counts = {key: counts[key] + hybrid_counts[key] for key in counts}
            return {**counts, "candidates": [], "warnings": []}

        raw_chapter_title = str(chapter.get("title") or "")
        chapter_title = _clean_chapter_title(raw_chapter_title)
        candidates = extract_candidate_terms_from_text(raw_text, raw_chapter_title)
        _, deterministic_corpus = _normalized_extraction_corpus(chapter_title, raw_text)
        chapter_number = int(chapter.get("chapter_number") or 0)
        repository = GlossaryRepository(self.db_path)
        counts = repository.record_extraction_candidates(
            book_id=book_id,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            extractor=DETERMINISTIC_EXTRACTOR,
            candidates=candidates,
            occurrence_corpus=deterministic_corpus,
        )
        warnings: list[dict] = []
        extraction_settings = self.get_extraction_settings(book_id)
        if extraction_settings["mode"] == "hybrid":
            hybrid, warnings, hybrid_corpus = self._hybrid_candidates(
                book_id=book_id,
                chapter_id=chapter_id,
                chapter_title=str(chapter.get("title") or ""),
                raw_text=raw_text,
                provider_id=str(extraction_settings["provider_id"]),
            )
            if hybrid is not None:
                hybrid_counts = repository.record_extraction_candidates(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                    extractor=HYBRID_EXTRACTOR,
                    candidates=hybrid,
                    occurrence_corpus=hybrid_corpus,
                )
                counts = {key: counts[key] + hybrid_counts[key] for key in counts}
                candidates = [*candidates, *hybrid]
        return {**counts, "candidates": candidates, "warnings": warnings}

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
