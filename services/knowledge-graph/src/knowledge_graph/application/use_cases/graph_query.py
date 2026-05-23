"""Query use cases for the Knowledge Graph REST API (S7).

Uses port interfaces (ABCs) from application.ports — never imports from
infrastructure directly (R25 / IG-LAYER-002 compliance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.ports.relation_summary_repository import RelationSummaryRepositoryPort
    from knowledge_graph.application.ports.repositories import (
        CanonicalEntityRepositoryPort,
        RelationEvidenceRepositoryPort,
        RelationRepositoryPort,
    )

_log = get_logger(__name__)  # type: ignore[no-any-return]


class GetEntityGraphUseCase:
    """Return entity row + neighbouring relation rows for an egocentric graph."""

    async def execute(
        self,
        entity_repo: CanonicalEntityRepositoryPort,
        relation_repo: RelationRepositoryPort,
        evidence_repo: RelationEvidenceRepositoryPort,
        summary_repo: RelationSummaryRepositoryPort,
        entity_id: UUID,
        min_confidence: float,
        semantic_mode: str | None,
        limit: int,
        evidence_limit: int = 3,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Return ``(entity_row, relation_rows, referenced_entities_map)``

        ``entity_row`` is ``None`` when the entity does not exist.
        ``referenced_entities_map`` maps ``str(entity_id)`` to entity row dicts
        for every entity referenced by the returned relations (excluding center).
        Each relation row is mutated in-place with ``evidence_snippets`` and
        ``relation_summary`` keys populated via single batch queries (no N+1).
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

        # Batch-fetch evidence snippets and summaries — single query each (BP-025 guard).
        # Merge results into relation_rows so the route layer can read them without
        # additional queries.
        if relation_rows:
            relation_ids: list[UUID] = []
            for r in relation_rows:
                rid = r.get("relation_id")
                if isinstance(rid, UUID):
                    relation_ids.append(rid)
            # Graceful degradation: if evidence or summary batch queries fail
            # (transient DB error, timeout), return empty maps rather than
            # propagating a 500 — the entity and relation data is still valid.
            try:
                evidence_map = await evidence_repo.get_evidence_snippets_batch(
                    relation_ids,
                    limit_per_relation=evidence_limit,
                )
            except Exception:
                _log.warning(
                    "graph_query_evidence_snippets_failed",
                    entity_id=str(entity_id),
                    relation_count=len(relation_ids),
                    exc_info=True,
                )
                evidence_map = {}

            try:
                summary_map = await summary_repo.get_current_summaries_batch(relation_ids)
            except Exception:
                _log.warning(
                    "graph_query_summaries_failed",
                    entity_id=str(entity_id),
                    relation_count=len(relation_ids),
                    exc_info=True,
                )
                summary_map = {}

            for r in relation_rows:
                rid = r.get("relation_id")
                r["evidence_snippets"] = evidence_map.get(rid, []) if isinstance(rid, UUID) else []  # type: ignore[index]
                r["relation_summary"] = summary_map.get(rid) if isinstance(rid, UUID) else None  # type: ignore[index]

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
