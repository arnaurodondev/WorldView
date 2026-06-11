"""GetRelationDetailUseCase — full edge detail for the Intelligence tab (PLAN-0099).

Assembles, for a single relation_id:
  - the full relation row (type, confidence, temporal validity, contra stats)
  - the current LLM summary (relation_summaries, is_current=true)
  - subject/object entity summaries (single get_batch call)
  - the evidence list (relation_evidence_raw via triple JOIN, newest first)

R25 compliance: depends only on port interfaces — never imports infrastructure.
R27 compliance: read-only — wired with the read-replica session in
``api/dependencies.py``.

Article metadata gap (documented): evidence rows carry ``source_document_id``
+ ``source_name``/``source_type`` only.  Article title/url/published_at live in
nlp_db / content-store (S5/S6) — R9 forbids reading them from here.  Clients
resolve them through the S9 gateway document/news endpoints when needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from knowledge_graph.application.ports.relation_summary_repository import RelationSummaryRepositoryPort
    from knowledge_graph.application.ports.repositories import (
        CanonicalEntityRepositoryPort,
        RelationEvidenceRepositoryPort,
        RelationRepositoryPort,
    )


@dataclass(frozen=True, slots=True)
class RelationDetailResult:
    """Aggregate returned by GetRelationDetailUseCase.

    ``relation`` is the raw row dict from RelationRepository.get_by_id with
    ``summary_authority`` added (computed at query time — NOT a cached column).
    ``subject_row`` / ``object_row`` are canonical_entities row dicts (None when
    the referenced entity row is missing — never raises).
    """

    relation: dict[str, Any]
    summary: dict[str, Any] | None
    subject_row: dict[str, Any] | None
    object_row: dict[str, Any] | None
    evidence: list[dict[str, Any]] = field(default_factory=list)


class GetRelationDetailUseCase:
    """Return the full relation detail + evidence, or None when not found."""

    async def execute(
        self,
        relation_repo: RelationRepositoryPort,
        evidence_repo: RelationEvidenceRepositoryPort,
        summary_repo: RelationSummaryRepositoryPort,
        entity_repo: CanonicalEntityRepositoryPort,
        relation_id: UUID,
        evidence_limit: int = 25,
    ) -> RelationDetailResult | None:
        relation = await relation_repo.get_by_id(relation_id)
        if relation is None:
            return None

        # summary_authority is computed at query time (same formula as the
        # graph endpoint): confidence * log1p(evidence_count); 0.0 when stale.
        confidence = relation.get("confidence")
        evidence_count = int(relation.get("evidence_count") or 0)
        relation["summary_authority"] = (
            round(float(confidence) * math.log1p(evidence_count), 6) if confidence is not None else 0.0
        )

        summary = await summary_repo.get_current(relation_id)
        evidence = await evidence_repo.get_detail_for_relation(relation_id, limit=evidence_limit)

        # Resolve subject/object entity summaries in one batch query (no N+1).
        subject_id = relation["subject_entity_id"]
        object_id = relation["object_entity_id"]
        rows = await entity_repo.get_batch([subject_id, object_id])
        rows_by_id = {str(r.get("entity_id")): r for r in rows}

        return RelationDetailResult(
            relation=relation,
            summary=summary,
            subject_row=rows_by_id.get(str(subject_id)),
            object_row=rows_by_id.get(str(object_id)),
            evidence=evidence,
        )
