"""GetEntityDetailUseCase — read-only entity detail with enrichment fields (PRD-0073 §9.6).

PLAN-0099 (Intelligence tab node detail): the use case now also assembles
aliases, the top relations (ranked by summary_authority) and the total
relation count, so GET /entities/{id} is rich enough for the frontend's
node-click panel without extra round-trips.

Recent mention / article counts are intentionally NOT included: they live in
nlp_db (S6) and R9 forbids cross-service DB access — the gateway exposes them
via GET /v1/entities/{id}/articles.

R25 compliance: this use case wraps repositories so that the API route file
never imports from the infrastructure layer directly.
R27 compliance: read-only — uses the read-replica session.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.ports.relation_summary_repository import RelationSummaryRepositoryPort
    from knowledge_graph.application.ports.repositories import RelationRepositoryPort
    from knowledge_graph.domain.models import CanonicalEntity
    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias import (
        EntityAliasRepository,
    )

# How many relations to fetch before ranking by summary_authority.  We fetch
# more than we return because list_for_entity orders by latest_evidence_at —
# the authority ranking happens in Python over this candidate window.
_TOP_RELATIONS_FETCH_LIMIT = 25
_TOP_RELATIONS_RETURN_LIMIT = 5


@dataclass(frozen=True, slots=True)
class EntityDetailResult:
    """Aggregate returned by GetEntityDetailUseCase (PLAN-0099)."""

    entity: CanonicalEntity
    aliases: list[dict[str, Any]] = field(default_factory=list)
    top_relations: list[dict[str, Any]] = field(default_factory=list)
    relation_count: int = 0


class GetEntityDetailUseCase:
    """Return the enriched entity detail for a single canonical entity.

    Args:
        repo: CanonicalEntityRepository bound to a read-only session.
        alias_repo: EntityAliasRepository (optional — aliases empty when None).
        relation_repo: RelationRepository (optional — relations empty when None).
        summary_repo: RelationSummaryRepository (optional — summaries null when None).

    The extra repos are optional so existing callers/tests that only care about
    the entity row keep working (BP-148 additive pattern).
    """

    def __init__(
        self,
        repo: CanonicalEntityRepository,
        alias_repo: EntityAliasRepository | None = None,
        relation_repo: RelationRepositoryPort | None = None,
        summary_repo: RelationSummaryRepositoryPort | None = None,
    ) -> None:
        self._repo = repo
        self._alias_repo = alias_repo
        self._relation_repo = relation_repo
        self._summary_repo = summary_repo

    async def execute(self, entity_id: UUID) -> EntityDetailResult | None:
        """Fetch and return the entity detail aggregate, or None if it does not exist."""
        entity = await self._repo.get_by_id(entity_id)
        if entity is None:
            return None

        aliases: list[dict[str, Any]] = []
        if self._alias_repo is not None:
            aliases = await self._alias_repo.get_for_entity(entity_id)

        top_relations: list[dict[str, Any]] = []
        relation_count = 0
        if self._relation_repo is not None:
            relation_count = await self._relation_repo.count_for_entity(entity_id)
            rows = await self._relation_repo.list_for_entity(
                entity_id,
                limit=_TOP_RELATIONS_FETCH_LIMIT,
            )
            top_relations = self._rank_top_relations(entity_id, rows)
            await self._attach_summaries(top_relations)
            await self._attach_counterpart_names(top_relations)

        return EntityDetailResult(
            entity=entity,
            aliases=aliases,
            top_relations=top_relations,
            relation_count=relation_count,
        )

    @staticmethod
    def _rank_top_relations(
        entity_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rank candidate relations by summary_authority and annotate direction.

        summary_authority = confidence * log1p(evidence_count) — same query-time
        formula as the graph endpoint (NOT a cached column).
        """
        annotated: list[dict[str, Any]] = []
        for r in rows:
            confidence = r.get("confidence")
            evidence_count = int(r.get("evidence_count") or 0)
            authority = float(confidence) * math.log1p(evidence_count) if confidence is not None else 0.0
            is_subject = r.get("subject_entity_id") == entity_id
            other_id = r.get("object_entity_id") if is_subject else r.get("subject_entity_id")
            annotated.append(
                {
                    **r,
                    "_authority": authority,
                    "direction": "outbound" if is_subject else "inbound",
                    "other_entity_id": other_id,
                },
            )
        annotated.sort(key=lambda r: r["_authority"], reverse=True)
        return annotated[:_TOP_RELATIONS_RETURN_LIMIT]

    async def _attach_summaries(self, top_relations: list[dict[str, Any]]) -> None:
        """Merge current LLM summaries into the top relations (single batch query)."""
        if self._summary_repo is None or not top_relations:
            return
        relation_ids = [r["relation_id"] for r in top_relations if isinstance(r.get("relation_id"), UUID)]
        summaries = await self._summary_repo.get_current_summaries_batch(relation_ids)
        for r in top_relations:
            rid = r.get("relation_id")
            r["relation_summary"] = summaries.get(rid) if isinstance(rid, UUID) else None

    async def _attach_counterpart_names(self, top_relations: list[dict[str, Any]]) -> None:
        """Resolve counterpart entity names/types in one get_batch call (no N+1)."""
        if not top_relations:
            return
        other_ids = [r["other_entity_id"] for r in top_relations if isinstance(r.get("other_entity_id"), UUID)]
        if not other_ids:
            return
        rows = await self._repo.get_batch(list(set(other_ids)))
        by_id = {str(row.get("entity_id")): row for row in rows}
        for r in top_relations:
            other = by_id.get(str(r.get("other_entity_id")))
            r["other_entity_name"] = other.get("canonical_name") if other else None
            r["other_entity_type"] = other.get("entity_type") if other else None
