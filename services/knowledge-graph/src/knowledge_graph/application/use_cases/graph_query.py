"""Query use cases for the Knowledge Graph REST API (S7).

Uses port interfaces (ABCs) from application.ports — never imports from
infrastructure directly (R25 / IG-LAYER-002 compliance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.ports.repositories import (
        CanonicalEntityRepositoryPort,
        RelationRepositoryPort,
    )


class GetEntityGraphUseCase:
    """Return entity row + neighbouring relation rows for an egocentric graph."""

    async def execute(
        self,
        entity_repo: CanonicalEntityRepositoryPort,
        relation_repo: RelationRepositoryPort,
        entity_id: UUID,
        min_confidence: float,
        semantic_mode: str | None,
        limit: int,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Return ``(entity_row, relation_rows, referenced_entities_map)``

        ``entity_row`` is ``None`` when the entity does not exist.
        ``referenced_entities_map`` maps ``str(entity_id)`` to entity row dicts
        for every entity referenced by the returned relations (excluding center).
        """
        entity_row = await entity_repo.get(entity_id)
        if entity_row is None:
            return None, [], {}

        relation_rows = await relation_repo.list_for_entity(
            entity_id=entity_id,
            min_confidence=min_confidence,
            semantic_mode=semantic_mode,
            limit=limit,
        )

        referenced_ids: set[UUID] = set()
        for r in relation_rows:
            sub = r["subject_entity_id"]
            obj = r["object_entity_id"]
            if isinstance(sub, UUID) and sub != entity_id:
                referenced_ids.add(sub)
            if isinstance(obj, UUID) and obj != entity_id:
                referenced_ids.add(obj)

        # F-017: replace per-entity get() loop with a single get_batch() call so
        # the N+1 query pattern is eliminated. For a graph with 50 relations this
        # reduces up to 100 individual queries to 1 batch query.
        entities_map: dict[str, dict[str, Any]] = {}
        if referenced_ids:
            batch_rows = await entity_repo.get_batch(list(referenced_ids))
            for row in batch_rows:
                row_id = row.get("entity_id")
                if row_id is not None:
                    entities_map[str(row_id)] = row

        return entity_row, relation_rows, entities_map


class ListRelationsUseCase:
    """Paginated, filtered relation list."""

    async def execute(
        self,
        relation_repo: RelationRepositoryPort,
        subject_entity_id: UUID | None,
        object_entity_id: UUID | None,
        canonical_type: str | None,
        semantic_mode: str | None,
        min_confidence: float | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        return await relation_repo.list_filtered(
            subject_entity_id=subject_entity_id,
            object_entity_id=object_entity_id,
            canonical_type=canonical_type,
            semantic_mode=semantic_mode,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )


class GetGraphStatsUseCase:
    """Aggregate knowledge graph statistics."""

    async def execute(self, relation_repo: RelationRepositoryPort) -> dict[str, Any]:
        return await relation_repo.get_stats()
