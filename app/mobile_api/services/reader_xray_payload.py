"""Normalize supported X-Ray payloads in memory, then publish one graph transaction."""
from copy import deepcopy
from pathlib import Path

from app.database.chapter_repository import list_chapters
from app.database.connection import get_connection
from app.database.reader_repository import (
    add_reader_entity, add_reader_entity_mention, add_reader_timeline_event, list_reader_xray_entities,
)


def normalize_reader_xray_payload(book_id: int, payload: dict, *, chapters: list[dict], existing_entities: list[dict],
    default_chapter_id: int | None, default_chapter_number: int, entity_type_for_name) -> dict:
    chapter_ids_by_number = {int(chapter.get("chapter_number") or 0): chapter["id"] for chapter in chapters}
    chapter_numbers_by_id = {chapter["id"]: int(chapter.get("chapter_number") or 0) for chapter in chapters}
    if default_chapter_id is not None and chapter_numbers_by_id.get(default_chapter_id) != default_chapter_number:
        raise ValueError("X-Ray default chapter does not belong to this book")
    entities_by_name = {entity["name"]: entity for entity in deepcopy(existing_entities)}
    changes, mentions, events = {}, [], []

    def upsert_entity(book_id, entities_by_name, *, name, entity_type, metadata, aliases=None,
                      description="", first_chapter_number=0, importance=40):
        existing = entities_by_name.get(name)
        merged_aliases = list(dict.fromkeys([
            *(existing.get("aliases", []) if existing else []),
            *(aliases or []),
        ]))
        merged_metadata = {
            **(existing.get("metadata", {}) if existing else {}),
            **metadata,
        }
        entity = {"name": name, "type": existing.get("type", entity_type) if existing else entity_type,
            "aliases": merged_aliases, "description": description or (existing.get("description", "") if existing else ""),
            "first_chapter_number": first_chapter_number or (existing.get("first_chapter_number", 0) if existing else 0),
            "importance": existing.get("importance", importance) if existing else importance, "metadata": merged_metadata}
        changes[name] = entity
        entities_by_name[name] = entity
        return entity

    def collect_mention(*, book_id, entity_name, chapter_id, chapter_number, paragraph_index=0, mention_text="", context=""):
        if chapter_numbers_by_id.get(chapter_id) != chapter_number:
            return
        mentions.append(dict(entity_name=entity_name, chapter_id=chapter_id, chapter_number=chapter_number,
                             paragraph_index=paragraph_index, mention_text=mention_text, context=context))

    def add_mention(book_id, *, entity, chapter_ids_by_number, chapter_number, default_chapter_id, mention_text, context):
        chapter_id = chapter_ids_by_number.get(chapter_number) or default_chapter_id
        collect_mention(book_id=book_id, entity_name=entity["name"], chapter_id=chapter_id,
                        chapter_number=chapter_number, mention_text=mention_text, context=context)

    def collect_event(*, book_id, chapter_id, chapter_number, **values):
        if chapter_numbers_by_id.get(chapter_id) == chapter_number:
            events.append(dict(chapter_id=chapter_id, chapter_number=chapter_number, **values))

    def ai_text(value: object) -> str:
        if isinstance(value, dict):
            for key in ("name", "label", "title", "text", "value", "id"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    def ai_payload_list(*keys: str, nested_keys: tuple[str, ...] | None = None) -> list[object]:
        items: list[object] = []
        nested_candidates = nested_keys or (
            "items",
            "entries",
            "nodes",
            "edges",
            "links",
            "events",
            "rankings",
            "relationships",
            "factions",
            "realms",
        )
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                items.extend(value)
            elif isinstance(value, dict):
                for nested_key in nested_candidates:
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, list):
                        items.extend(nested_value)
                        break
        return items

    graph_node_names: dict[str, str] = {}
    graph_payload = payload.get("relationship_graph")
    if isinstance(graph_payload, dict):
        for raw_node in ai_payload_list("relationship_graph", nested_keys=("nodes", "entities")):
            if not isinstance(raw_node, dict):
                continue
            node_name = ai_text(raw_node.get("name") or raw_node.get("label") or raw_node.get("title"))
            if not node_name:
                continue
            for key in ("id", "key", "name", "label"):
                node_id = str(raw_node.get(key) or "").strip()
                if node_id:
                    graph_node_names[node_id] = node_name

    allowed_entity_types = {"character", "faction", "location", "item", "realm", "skill"}
    raw_entities = ai_payload_list("entities", "entity_profiles")
    if isinstance(graph_payload, dict):
        raw_entities.extend(ai_payload_list("relationship_graph", nested_keys=("nodes", "entities")))
    if isinstance(raw_entities, list):
        for raw in raw_entities:
            if not isinstance(raw, dict):
                continue
            name = ai_text(raw.get("name") or raw.get("label") or raw.get("title"))
            if not name:
                continue
            raw_type = str(raw.get("type") or raw.get("entity_type") or raw.get("node_type") or "").strip()
            entity_type = raw_type if raw_type in allowed_entity_types else entity_type_for_name(name)
            chapter_number = int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0)
            raw_aliases = raw.get("aliases", [])
            aliases = (
                [ai_text(alias) for alias in raw_aliases if ai_text(alias) and ai_text(alias) != name]
                if isinstance(raw_aliases, list)
                else []
            )
            metadata = dict(raw.get("metadata")) if isinstance(raw.get("metadata"), dict) else {}
            metadata["source"] = metadata.get("source") or "ai_xray_profile"
            for source_key, target_key in (
                ("faction", "faction"),
                ("sect", "faction"),
                ("organization", "faction"),
                ("power_rank", "power_rank"),
                ("rank", "power_rank"),
                ("power_level", "power_rank"),
                ("power_label", "power_label"),
                ("realm", "power_label"),
                ("rank_label", "power_label"),
                ("power_basis", "power_basis"),
                ("basis", "power_basis"),
                ("evidence", "power_basis"),
            ):
                if raw.get(source_key) not in (None, ""):
                    metadata[target_key] = raw.get(source_key)
            raw_relationships = raw.get("relationships", [])
            if isinstance(raw_relationships, list):
                relationships: list[dict] = []
                for relationship in raw_relationships:
                    if not isinstance(relationship, dict):
                        continue
                    target = str(relationship.get("target") or "").strip()
                    if not target:
                        continue
                    relationships.append(
                        {
                            "target": target,
                            "relation": str(relationship.get("relation") or relationship.get("type") or "liên hệ").strip(),
                            "evidence": str(relationship.get("evidence") or relationship.get("summary") or "").strip(),
                            "chapter_number": int(relationship.get("chapter_number") or chapter_number or 0),
                            "strength": relationship.get("strength") if isinstance(relationship.get("strength"), int | float) else 0.75,
                            "source_type": "ai",
                        }
                    )
                if relationships:
                    metadata["relationships"] = [
                        *(metadata.get("relationships") if isinstance(metadata.get("relationships"), list) else []),
                        *relationships,
                    ]

            entity = upsert_entity(
                book_id,
                entities_by_name,
                name=name,
                entity_type=entity_type,
                aliases=aliases,
                description=str(raw.get("description") or "").strip(),
                first_chapter_number=chapter_number,
                importance=int(raw.get("importance") or 75),
                metadata=metadata,
            )
            add_mention(
                book_id,
                entity=entity,
                chapter_ids_by_number=chapter_ids_by_number,
                chapter_number=chapter_number,
                default_chapter_id=default_chapter_id,
                mention_text=name,
                context=str(raw.get("evidence") or raw.get("description") or name).strip(),
            )

    def typed_ai_int(value: object, fallback: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def typed_ai_values(value: object) -> list[str]:
        if isinstance(value, list):
            return [text for item in value if (text := ai_text(item))]
        text = ai_text(value)
        return [text] if text else []

    def typed_ai_metadata_value(value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, list):
            values = [text for item in value if (text := ai_text(item))]
            return values or None
        return value

    def ensure_ai_link_entity(
        *,
        name: str,
        entity_type: str,
        chapter_number: int,
        context: str,
        importance: int = 50,
    ) -> dict:
        existing = entities_by_name.get(name)
        if existing:
            return existing
        entity = upsert_entity(
            book_id,
            entities_by_name,
            name=name,
            entity_type=entity_type,
            metadata={"source": "ai_xray_enrichment"},
            first_chapter_number=chapter_number,
            importance=importance,
        )
        add_mention(
            book_id,
            entity=entity,
            chapter_ids_by_number=chapter_ids_by_number,
            chapter_number=chapter_number,
            default_chapter_id=default_chapter_id,
            mention_text=name,
            context=context or name,
        )
        return entity

    def add_ai_relationship(
        *,
        source_name: str,
        target_name: str,
        relation: str,
        evidence: str,
        chapter_number: int,
        source_entity_type: str | None = None,
        target_entity_type: str | None = None,
    ) -> None:
        source_entity = ensure_ai_link_entity(
            name=source_name,
            entity_type=source_entity_type or entity_type_for_name(source_name),
            chapter_number=chapter_number,
            context=evidence,
            importance=65,
        )
        ensure_ai_link_entity(
            name=target_name,
            entity_type=target_entity_type or entity_type_for_name(target_name),
            chapter_number=chapter_number,
            context=evidence,
            importance=55,
        )
        source_metadata = dict(source_entity.get("metadata", {})) if source_entity else {}
        relationships = source_metadata.get("relationships")
        if not isinstance(relationships, list):
            relationships = []
        next_relationship = {
            "target": target_name,
            "relation": relation,
            "evidence": evidence,
            "chapter_number": chapter_number,
            "strength": 0.8,
            "source_type": "ai",
        }
        if not any(
            isinstance(item, dict)
            and item.get("target") == target_name
            and item.get("relation") == relation
            and int(item.get("chapter_number") or 0) == chapter_number
            for item in relationships
        ):
            relationships.append(next_relationship)
        source_metadata["relationships"] = relationships
        source_metadata["source"] = source_metadata.get("source") or "ai_xray_enrichment"
        linked_entity = upsert_entity(
            book_id,
            entities_by_name,
            name=source_name,
            entity_type=source_entity_type or entity_type_for_name(source_name),
            metadata=source_metadata,
            first_chapter_number=chapter_number,
            importance=65,
        )
        add_mention(
            book_id,
            entity=linked_entity,
            chapter_ids_by_number=chapter_ids_by_number,
            chapter_number=chapter_number,
            default_chapter_id=default_chapter_id,
            mention_text=source_name,
            context=evidence or source_name,
        )

    def apply_typed_ai_entities(
        collection_keys: str | tuple[str, ...],
        entity_type: str,
        *,
        metadata_keys: tuple[tuple[str, str], ...],
        link_keys: tuple[tuple[str, str], ...] = (),
        nested_keys: tuple[str, ...] | None = None,
        outbound_link_keys: tuple[tuple[str, str], ...] = (),
        default_importance: int = 65,
    ) -> None:
        keys = (collection_keys,) if isinstance(collection_keys, str) else collection_keys
        raw_collection = ai_payload_list(*keys, nested_keys=nested_keys)
        for raw in raw_collection:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            chapter_number = typed_ai_int(raw.get("chapter_number") or default_chapter_number, default_chapter_number)
            raw_aliases = raw.get("aliases", [])
            aliases = (
                [str(alias).strip() for alias in raw_aliases if str(alias).strip() and str(alias).strip() != name]
                if isinstance(raw_aliases, list)
                else []
            )
            metadata = dict(raw.get("metadata")) if isinstance(raw.get("metadata"), dict) else {}
            metadata["source"] = metadata.get("source") or "ai_xray_enrichment"
            for source_key, target_key in metadata_keys:
                value = typed_ai_metadata_value(raw.get(source_key))
                if value is not None:
                    metadata[target_key] = value
            entity = upsert_entity(
                book_id,
                entities_by_name,
                name=name,
                entity_type=entity_type,
                aliases=aliases,
                description=str(raw.get("description") or "").strip(),
                first_chapter_number=chapter_number,
                importance=typed_ai_int(raw.get("importance"), default_importance),
                metadata=metadata,
            )
            context = str(raw.get("evidence") or raw.get("description") or name).strip()
            add_mention(
                book_id,
                entity=entity,
                chapter_ids_by_number=chapter_ids_by_number,
                chapter_number=chapter_number,
                default_chapter_id=default_chapter_id,
                mention_text=name,
                context=context,
            )
            for source_key, relation in link_keys:
                for source_name in typed_ai_values(raw.get(source_key)):
                    add_ai_relationship(
                        source_name=source_name,
                        target_name=name,
                        relation=relation,
                        evidence=context,
                        chapter_number=chapter_number,
                        target_entity_type=entity_type,
                    )
            for target_key, relation in outbound_link_keys:
                for target_name in typed_ai_values(raw.get(target_key)):
                    add_ai_relationship(
                        source_name=name,
                        target_name=target_name,
                        relation=relation,
                        evidence=context,
                        chapter_number=chapter_number,
                        source_entity_type=entity_type,
                        target_entity_type=entity_type,
                    )

    apply_typed_ai_entities(
        ("locations", "places", "world_map"),
        "location",
        nested_keys=("locations", "places", "nodes", "items", "entries"),
        metadata_keys=(
            ("region", "region"),
            ("parent", "parent"),
            ("area", "region"),
            ("faction", "faction"),
            ("factions", "factions"),
            ("sect", "faction"),
            ("significance", "significance"),
            ("role", "significance"),
        ),
        link_keys=(
            ("characters", "xuất hiện tại"),
            ("people", "xuất hiện tại"),
            ("participants", "xuất hiện tại"),
            ("factions", "có thế lực tại"),
            ("sects", "có thế lực tại"),
            ("organizations", "có thế lực tại"),
        ),
        outbound_link_keys=(("parent", "thuộc địa vực"),),
        default_importance=58,
    )
    apply_typed_ai_entities(
        ("items", "equipment", "treasures", "artifacts"),
        "item",
        metadata_keys=(
            ("owner", "owner"),
            ("owners", "owners"),
            ("wielder", "owner"),
            ("category", "category"),
            ("grade", "grade"),
            ("rank", "rank"),
            ("effect", "effect"),
            ("origin", "origin"),
            ("faction", "faction"),
        ),
        link_keys=(("owner", "sở hữu"), ("wielder", "sở hữu")),
        default_importance=60,
    )
    apply_typed_ai_entities(
        ("skills", "techniques", "abilities"),
        "skill",
        metadata_keys=(
            ("user", "user"),
            ("users", "users"),
            ("owner", "user"),
            ("category", "category"),
            ("realm", "realm"),
            ("grade", "grade"),
            ("effect", "effect"),
            ("faction", "faction"),
        ),
        link_keys=(("user", "tu luyện"), ("owner", "tu luyện")),
        default_importance=62,
    )
    apply_typed_ai_entities(
        ("realms", "realm_hierarchy", "cultivation_realms"),
        "realm",
        metadata_keys=(
            ("order", "order"),
            ("rank", "rank"),
            ("parent", "parent"),
            ("previous", "previous"),
            ("next", "next"),
            ("category", "category"),
            ("evidence", "evidence"),
        ),
        outbound_link_keys=(
            ("next", "tiến tới cảnh giới"),
            ("previous", "sau cảnh giới"),
            ("parent", "thuộc hệ cảnh giới"),
        ),
        default_importance=68,
    )

    raw_factions = ai_payload_list("factions", "faction_tree", nested_keys=("factions", "nodes", "items", "entries"))
    if isinstance(raw_factions, list):
        def apply_ai_faction(raw: object, *, inherited_parent: str = "", depth: int = 0) -> None:
            if depth > 4:
                return
            if not isinstance(raw, dict):
                name = ai_text(raw)
                if not name:
                    return
                raw = {"name": name}
            name = ai_text(raw.get("name") or raw.get("label") or raw.get("title"))
            if not name:
                return
            chapter_number = typed_ai_int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number, default_chapter_number)
            parent = str(raw.get("parent") or raw.get("parent_faction") or inherited_parent or "").strip()
            faction_entity = upsert_entity(
                book_id,
                entities_by_name,
                name=name,
                entity_type="faction",
                description=str(raw.get("description") or "").strip(),
                first_chapter_number=chapter_number,
                importance=70,
                metadata={
                    "parent": parent,
                    "source": "ai_xray_enrichment",
                },
            )
            faction_chapter_id = chapter_ids_by_number.get(chapter_number) or default_chapter_id
            if faction_chapter_id:
                collect_mention(
                    book_id=book_id,
                    entity_name=faction_entity["name"],
                    chapter_id=faction_chapter_id,
                    chapter_number=chapter_number,
                    paragraph_index=0,
                    mention_text=name,
                    context=str(raw.get("description") or name).strip(),
                )
            members = [
                *typed_ai_values(raw.get("members")),
                *typed_ai_values(raw.get("member_names")),
            ]
            for member_name in members:
                if not member_name:
                    continue
                member_entity = entities_by_name.get(member_name)
                member_metadata = dict(member_entity.get("metadata", {})) if member_entity else {}
                member_metadata["faction"] = name
                member_metadata["source"] = member_metadata.get("source") or "ai_xray_enrichment"
                member_entity = upsert_entity(
                    book_id,
                    entities_by_name,
                    name=member_name,
                    entity_type="character",
                    metadata=member_metadata,
                    first_chapter_number=member_entity.get("first_chapter_number", chapter_number) if member_entity else chapter_number,
                )
                add_mention(
                    book_id,
                    entity=member_entity,
                    chapter_ids_by_number=chapter_ids_by_number,
                    chapter_number=chapter_number,
                    default_chapter_id=default_chapter_id,
                    mention_text=member_name,
                    context=str(raw.get("description") or name).strip(),
                )

            children = raw.get("children") or raw.get("child_factions") or raw.get("subfactions") or []
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        child_payload = dict(child)
                        child_payload.setdefault("parent", name)
                        child_payload.setdefault("chapter_number", chapter_number)
                        apply_ai_faction(child_payload, inherited_parent=name, depth=depth + 1)
                    else:
                        child_name = ai_text(child)
                        if child_name:
                            apply_ai_faction(
                                {"name": child_name, "parent": name, "chapter_number": chapter_number},
                                inherited_parent=name,
                                depth=depth + 1,
                            )

        for raw in raw_factions:
            apply_ai_faction(raw)

    raw_power_rankings = ai_payload_list("power_rankings", "power_ranking", "power_levels")
    if isinstance(raw_power_rankings, list):
        for raw in raw_power_rankings:
            if not isinstance(raw, dict):
                continue
            name = ai_text(raw.get("name") or raw.get("character") or raw.get("entity") or raw.get("label"))
            if not name:
                continue
            entity = entities_by_name.get(name)
            metadata = dict(entity.get("metadata", {})) if entity else {}
            rank_value = raw.get("rank") if raw.get("rank") is not None else raw.get("power_rank")
            if rank_value is None:
                rank_value = raw.get("power_level")
            if rank_value is not None:
                metadata["power_rank"] = rank_value
            metadata["power_label"] = ai_text(raw.get("label") or raw.get("realm") or raw.get("power_label") or raw.get("rank_label"))
            metadata["power_basis"] = ai_text(raw.get("basis") or raw.get("reason") or raw.get("evidence"))
            faction = ai_text(raw.get("faction") or raw.get("sect") or raw.get("organization"))
            if faction:
                metadata["faction"] = faction
            metadata["source"] = metadata.get("source") or "ai_xray_enrichment"
            chapter_number = int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0)
            ranked_entity = upsert_entity(
                book_id,
                entities_by_name,
                name=name,
                entity_type="character",
                metadata=metadata,
                first_chapter_number=entity.get("first_chapter_number", chapter_number) if entity else chapter_number,
            )
            add_mention(
                book_id,
                entity=ranked_entity,
                chapter_ids_by_number=chapter_ids_by_number,
                chapter_number=chapter_number,
                default_chapter_id=default_chapter_id,
                mention_text=name,
                context=str(raw.get("basis") or raw.get("label") or name).strip(),
            )

    raw_relationships = ai_payload_list(
        "relationships",
        "relationship_graph",
        "character_relationships",
        nested_keys=("relationships", "edges", "links", "items", "entries"),
    )
    if isinstance(raw_relationships, list):
        for raw in raw_relationships:
            if not isinstance(raw, dict):
                continue
            source_ref = ai_text(
                raw.get("source")
                or raw.get("from")
                or raw.get("source_id")
                or raw.get("from_id")
                or raw.get("source_name")
                or raw.get("from_name")
                or raw.get("source_label")
                or raw.get("actor")
            )
            target_ref = ai_text(
                raw.get("target")
                or raw.get("to")
                or raw.get("target_id")
                or raw.get("to_id")
                or raw.get("target_name")
                or raw.get("to_name")
                or raw.get("target_label")
                or raw.get("object")
            )
            source = graph_node_names.get(source_ref, source_ref)
            target = graph_node_names.get(target_ref, target_ref)
            if not source or not target:
                continue
            source_entity = entities_by_name.get(source)
            if not source_entity:
                source_entity = upsert_entity(
                    book_id,
                    entities_by_name,
                    name=source,
                    entity_type=str(raw.get("source_entity_type") or raw.get("source_type") or "character"),
                    metadata={"source": "ai_xray_enrichment"},
                    first_chapter_number=int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0),
                )
                source_chapter_number = int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0)
                source_chapter_id = chapter_ids_by_number.get(source_chapter_number) or default_chapter_id
                if source_chapter_id:
                    add_mention(
                        book_id,
                        entity=source_entity,
                        chapter_ids_by_number=chapter_ids_by_number,
                        chapter_number=source_chapter_number,
                        default_chapter_id=source_chapter_id,
                        mention_text=source,
                        context=str(raw.get("evidence") or source).strip(),
                    )
            if target not in entities_by_name:
                target_entity = upsert_entity(
                    book_id,
                    entities_by_name,
                    name=target,
                    entity_type=str(raw.get("target_entity_type") or raw.get("target_type") or "character"),
                    metadata={"source": "ai_xray_enrichment"},
                    first_chapter_number=int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0),
                )
                target_chapter_number = int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0)
                target_chapter_id = chapter_ids_by_number.get(target_chapter_number) or default_chapter_id
                if target_chapter_id:
                    add_mention(
                        book_id,
                        entity=target_entity,
                        chapter_ids_by_number=chapter_ids_by_number,
                        chapter_number=target_chapter_number,
                        default_chapter_id=target_chapter_id,
                        mention_text=target,
                        context=str(raw.get("evidence") or target).strip(),
                    )
            metadata = dict(source_entity.get("metadata", {}))
            relationships = metadata.get("relationships")
            if not isinstance(relationships, list):
                relationships = []
            next_relationship = {
                "target": target,
                "relation": ai_text(raw.get("relation") or raw.get("label") or raw.get("type") or "liên hệ"),
                "evidence": ai_text(raw.get("evidence") or raw.get("summary")),
                "chapter_number": int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0),
                "strength": (
                    raw.get("strength")
                    if isinstance(raw.get("strength"), int | float)
                    else raw.get("weight") if isinstance(raw.get("weight"), int | float) else 0.75
                ),
                "source_type": "ai",
            }
            duplicate = any(
                isinstance(item, dict)
                and item.get("target") == next_relationship["target"]
                and item.get("relation") == next_relationship["relation"]
                and int(item.get("chapter_number") or 0) == next_relationship["chapter_number"]
                for item in relationships
            )
            if not duplicate:
                relationships.append(next_relationship)
            metadata["relationships"] = relationships
            metadata["source"] = metadata.get("source") or "ai_xray_enrichment"
            upsert_entity(
                book_id,
                entities_by_name,
                name=source,
                entity_type=source_entity.get("type", "character"),
                metadata=metadata,
                first_chapter_number=source_entity.get("first_chapter_number", default_chapter_number),
            )

    raw_timeline = ai_payload_list("timeline", "timeline_events", "events")
    if isinstance(raw_timeline, list):
        for raw in raw_timeline:
            if not isinstance(raw, dict):
                continue
            title = ai_text(raw.get("title") or raw.get("event") or raw.get("name") or raw.get("label"))
            if not title:
                continue
            chapter_number = int(raw.get("chapter_number") or raw.get("chapter") or default_chapter_number or 0)
            chapter_id = chapter_ids_by_number.get(chapter_number) or default_chapter_id
            if not chapter_id:
                continue
            event_entity_types: dict[str, str] = {}
            event_entities: list[str] = []

            def add_event_entities(value: object, entity_type: str | None = None) -> None:
                for entity_name in typed_ai_values(value):
                    if entity_name not in event_entities:
                        event_entities.append(entity_name)
                    if entity_type and entity_name not in event_entity_types:
                        event_entity_types[entity_name] = entity_type

            add_event_entities(raw.get("entities"))
            add_event_entities(raw.get("participants"))
            add_event_entities(raw.get("characters"), "character")
            add_event_entities(raw.get("people"), "character")
            add_event_entities(raw.get("locations"), "location")
            add_event_entities(raw.get("places"), "location")
            add_event_entities(raw.get("factions"), "faction")
            add_event_entities(raw.get("sects"), "faction")
            add_event_entities(raw.get("organizations"), "faction")
            add_event_entities(raw.get("items"), "item")
            add_event_entities(raw.get("treasures"), "item")
            add_event_entities(raw.get("artifacts"), "item")
            add_event_entities(raw.get("realms"), "realm")
            add_event_entities(raw.get("cultivation_realms"), "realm")
            add_event_entities(raw.get("skills"), "skill")
            add_event_entities(raw.get("techniques"), "skill")
            collect_event(
                book_id=book_id,
                chapter_id=chapter_id,
                chapter_number=chapter_number,
                event_order=int(raw.get("event_order") or raw.get("order") or 1),
                title=title,
                summary=ai_text(raw.get("summary") or raw.get("description")),
                entities=event_entities,
            )
            for entity_name in event_entities:
                entity = upsert_entity(
                    book_id,
                    entities_by_name,
                    name=entity_name,
                    entity_type=event_entity_types.get(entity_name) or entity_type_for_name(entity_name),
                    description="",
                    first_chapter_number=chapter_number,
                    importance=55,
                    metadata={"source": "ai_xray_timeline"},
                )
                collect_mention(
                    book_id=book_id,
                    entity_name=entity["name"],
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                    paragraph_index=0,
                    mention_text=entity_name,
                    context=str(raw.get("summary") or title).strip(),
                )

    return {"entities": list(changes.values()), "mentions": mentions, "events": events}


def apply_reader_xray_payload(db_path: Path, book_id: int, payload: dict, *, default_chapter_id,
                             default_chapter_number, entity_type_for_name) -> None:
    graph = normalize_reader_xray_payload(book_id, payload, chapters=list_chapters(db_path, book_id),
        existing_entities=list_reader_xray_entities(db_path, book_id), default_chapter_id=default_chapter_id,
        default_chapter_number=default_chapter_number, entity_type_for_name=entity_type_for_name)
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current_chapters = {row["id"]: row["chapter_number"] for row in conn.execute(
            "SELECT id, chapter_number FROM chapters WHERE book_id = ? AND deleted_at IS NULL", (book_id,))}
        for item in [*graph["mentions"], *graph["events"]]:
            if current_chapters.get(item["chapter_id"]) != item["chapter_number"]:
                raise ValueError("Xray chapter has changed; regenerate the analysis")
        ids = {row["name"]: row["id"] for row in conn.execute(
            "SELECT id, name FROM reader_entities WHERE book_id = ?", (book_id,))}
        for entity in graph["entities"]:
            values = dict(entity)
            values["entity_type"] = values.pop("type")
            saved = add_reader_entity(db_path, book_id=book_id, connection=conn, **values)
            ids[entity["name"]] = saved["id"]
        for mention in graph["mentions"]:
            values = dict(mention)
            name = values.pop("entity_name")
            add_reader_entity_mention(db_path, book_id=book_id, entity_id=ids[name], connection=conn, **values)
        for event in graph["events"]:
            add_reader_timeline_event(db_path, book_id=book_id, connection=conn, **event)
        conn.commit()
