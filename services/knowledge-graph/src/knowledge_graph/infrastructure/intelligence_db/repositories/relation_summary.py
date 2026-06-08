"""RelationSummary repository (PRD §6.7 Block 13C + Wave C-3).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Insert pattern: set old summaries ``is_current=false`` THEN insert new one
within the same transaction to maintain the unique constraint on
``(relation_id) WHERE is_current = true``.

Wave C-3 adds ``search_by_embedding``: HNSW ANN cosine search on
``summary_embedding`` joining ``relations`` + ``canonical_entities``.
``summary_authority`` is computed in Python (NOT a stored column).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.relation_summary_repository import (
    RelationSummaryRepositoryPort,
    RelationSummarySearchResult,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class RelationSummaryRepository(RelationSummaryRepositoryPort):
    """Write/read repository for ``relation_summaries``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, relation_id: UUID) -> dict[str, object] | None:
        """Fetch the current summary for a relation (is_current=true)."""
        result = await self._session.execute(
            text("""
SELECT summary_id, summary_text, evidence_count, evidence_hash,
       model_id, prompt_template_id, generated_at, generation_trigger
FROM relation_summaries
WHERE relation_id = :relation_id AND is_current = true
LIMIT 1
"""),
            {"relation_id": str(relation_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "summary_id": UUID(str(row[0])),
            "summary_text": row[1],
            "evidence_count": int(row[2]),
            "evidence_hash": row[3],
            "model_id": row[4],
            "prompt_template_id": UUID(str(row[5])),
            "generated_at": row[6],
            "generation_trigger": row[7],
        }

    async def insert_new(
        self,
        relation_id: UUID,
        summary_text: str,
        evidence_count: int,
        evidence_hash: str,
        model_id: str,
        prompt_template_id: UUID,
        generation_trigger: str,
    ) -> UUID:
        """Insert a new current summary, retiring any previous one.

        Pattern (must run in a single transaction):
        1. Set old summaries ``is_current = false``.
        2. Insert new summary with ``is_current = true``.
        """
        # Step 1 — retire old summaries
        await self._session.execute(
            text("""
UPDATE relation_summaries
SET is_current = false
WHERE relation_id = :relation_id AND is_current = true
"""),
            {"relation_id": str(relation_id)},
        )

        # Step 2 — insert new current summary
        result = await self._session.execute(
            text("""
INSERT INTO relation_summaries (
    relation_id, summary_text, evidence_count, evidence_hash,
    model_id, prompt_template_id, is_current, generation_trigger
) VALUES (
    :relation_id, :summary_text, :evidence_count, :evidence_hash,
    :model_id, :prompt_template_id, true, :generation_trigger
)
RETURNING summary_id
"""),
            {
                "relation_id": str(relation_id),
                "summary_text": summary_text,
                "evidence_count": evidence_count,
                "evidence_hash": evidence_hash,
                "model_id": model_id,
                "prompt_template_id": str(prompt_template_id),
                "generation_trigger": generation_trigger,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    async def update_embedding(
        self,
        summary_id: UUID,
        embedding: list[float],
        model_id: str,
        embedded_at: datetime,
    ) -> None:
        """Persist a computed embedding for an existing summary row (Worker 13F).

        Wave A-2 / DEF-022: also records ``summary_embedding_model_id`` and
        ``summary_last_embedded_at`` (migration 0027) so the ANN index can be
        audited for mixed-model drift and re-embedded selectively.
        """
        # pgvector binding: asyncpg cannot bind a Python list to a ``vector``
        # column directly (raises ``DataError: expected str, got list``).
        # Format as pgvector text literal ``[v1,v2,...]`` and CAST in SQL —
        # matches the canonical pattern used in ``entity_embedding_state``
        # (see FQA-2 / BP for pgvector binding regression).
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        await self._session.execute(
            text("""
UPDATE relation_summaries
SET summary_embedding             = CAST(:embedding AS vector),
    summary_embedding_model_id    = :model_id,
    summary_last_embedded_at      = :embedded_at
WHERE summary_id = :summary_id
"""),
            {
                "summary_id": str(summary_id),
                "embedding": embedding_str,
                "model_id": model_id,
                "embedded_at": embedded_at,
            },
        )

    async def search_by_embedding(
        self,
        query_embedding: list[float],
        *,
        entity_ids: list[UUID] | None = None,
        min_confidence: float = 0.30,
        relation_types: list[str] | None = None,
        semantic_mode: str | None = None,
        top_k: int = 15,
    ) -> list[RelationSummarySearchResult]:
        """ANN cosine search on ``relation_summaries.summary_embedding`` (Wave C-3).

        Uses the HNSW index ``idx_relation_summary_emb_hnsw`` (is_current=true,
        summary_embedding IS NOT NULL). Joins ``relations`` and
        ``canonical_entities`` to return entity names and relation metadata.

        ``summary_authority`` is computed at fetch time:
        ``confidence * log1p(evidence_count)`` — NOT a stored column.
        """
        # Normalize empty list to None — ANY(ARRAY[]) always evaluates FALSE, not "no filter"
        if not entity_ids:
            entity_ids = None

        result = await self._session.execute(
            text("""
SELECT rs.relation_id, r.subject_entity_id, r.object_entity_id,
       se.canonical_name AS subject_name, oe.canonical_name AS object_name,
       r.canonical_type, rs.summary_text, r.confidence, r.evidence_count,
       r.latest_evidence_at, r.semantic_mode,
       rs.summary_embedding <=> CAST(:query_embedding AS vector) AS distance
FROM relation_summaries rs
JOIN relations r ON rs.relation_id = r.relation_id
JOIN canonical_entities se ON r.subject_entity_id = se.entity_id
JOIN canonical_entities oe ON r.object_entity_id = oe.entity_id
WHERE rs.is_current = true
  AND rs.summary_embedding IS NOT NULL
  AND r.confidence >= :min_confidence
  AND (CAST(:entity_ids AS uuid[]) IS NULL
        OR r.subject_entity_id = ANY(CAST(:entity_ids AS uuid[]))
        OR r.object_entity_id = ANY(CAST(:entity_ids AS uuid[])))
  AND (CAST(:relation_types AS text[]) IS NULL OR r.canonical_type = ANY(CAST(:relation_types AS text[])))
  AND (CAST(:semantic_mode AS text) IS NULL OR r.semantic_mode = CAST(:semantic_mode AS text))
ORDER BY distance ASC
LIMIT :top_k
"""),
            {
                "query_embedding": str(query_embedding),
                "min_confidence": min_confidence,
                "entity_ids": [str(e) for e in entity_ids] if entity_ids is not None else None,
                "relation_types": relation_types if relation_types else None,
                "semantic_mode": semantic_mode,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [
            RelationSummarySearchResult(
                relation_id=UUID(str(r[0])),
                subject_entity_id=UUID(str(r[1])),
                object_entity_id=UUID(str(r[2])),
                subject_canonical_name=str(r[3]),
                object_canonical_name=str(r[4]),
                canonical_type=str(r[5]),
                summary=str(r[6]),
                confidence=float(r[7]),
                evidence_count=int(r[8]),
                latest_evidence_at=r[9],
                semantic_mode=str(r[10]),
                summary_authority=float(r[7]) * math.log1p(int(r[8])),
            )
            for r in rows
        ]

    async def get_current_summaries_batch(
        self,
        relation_ids: list[UUID],
    ) -> dict[UUID, str | None]:
        """Return current summary_text per relation in a single ANY(:ids) query.

        Only is_current=true rows are returned.  Absent relation_ids are not in the dict.
        # TODO(PRD-0074): upgrade to denormalized current_summary_text scalar on relations
        """
        if not relation_ids:
            return {}

        result = await self._session.execute(
            text("""
SELECT relation_id, summary_text
FROM   relation_summaries
WHERE  relation_id = ANY(CAST(:relation_ids AS uuid[]))
  AND  is_current  = true
"""),
            {"relation_ids": [str(rid) for rid in relation_ids]},
        )
        rows = result.fetchall()
        return {UUID(str(r[0])): str(r[1]) if r[1] else None for r in rows}
