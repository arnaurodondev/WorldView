"""Claims and contradiction-link read repository (Wave C-1).

Queries the ``claims`` (RANGE-partitioned) and
``relation_contradiction_links`` tables in intelligence_db.

S7 does NOT own intelligence_db DDL — all queries use raw SQL via ``text()``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.claim_repository import (
    ClaimRepositoryPort,
    ClaimSearchResult,
    ContradictionData,
    ContradictionSideData,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ClaimRepository(ClaimRepositoryPort):
    """Read-only access to ``claims`` and ``relation_contradiction_links``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_claims(
        self,
        entity_ids: list[UUID],
        *,
        claim_types: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_confidence: float = 0.45,
        top_k: int = 20,
    ) -> list[ClaimSearchResult]:
        """Return claims for *entity_ids* ordered by ``extraction_confidence DESC``.

        Optional filters: claim_types, date range, minimum extraction confidence.
        The ``claims`` table is RANGE-partitioned by ``created_at``.
        """
        # BP-180: asyncpg raises AmbiguousParameterError when a Python None is
        # bound to a parameter used in "IS NULL" — it cannot infer the PostgreSQL
        # type from None alone.  Fix: CAST(:param AS TYPE) IS NULL so the type
        # is always explicit.  Applied to entity_ids, claim_types, AND the date
        # params (date_from/date_to were previously unfixed, causing the error
        # seen on every claim search that includes optional date filters).
        result = await self._session.execute(
            text("""
SELECT claim_id, subject_entity_id, claim_type, polarity, claim_text,
       extraction_confidence, doc_id, created_at
FROM claims
WHERE subject_entity_id = ANY(CAST(:entity_ids AS UUID[]))
  AND (CAST(:claim_types AS TEXT[]) IS NULL OR claim_type = ANY(CAST(:claim_types AS TEXT[])))
  AND (CAST(:date_from AS DATE) IS NULL OR created_at >= CAST(:date_from AS DATE))
  AND (CAST(:date_to   AS DATE) IS NULL OR created_at <= CAST(:date_to   AS DATE))
  AND extraction_confidence >= :min_confidence
ORDER BY extraction_confidence DESC
LIMIT :top_k
"""),
            {
                "entity_ids": [str(e) for e in entity_ids],
                "claim_types": claim_types if claim_types else None,
                "date_from": date_from,
                "date_to": date_to,
                "min_confidence": min_confidence,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [
            ClaimSearchResult(
                claim_id=UUID(str(r[0])),
                subject_entity_id=UUID(str(r[1])),
                claim_type=str(r[2]),
                polarity=str(r[3]),
                claim_text=str(r[4]),
                extraction_confidence=float(r[5]),
                doc_id=UUID(str(r[6])) if r[6] else None,
                created_at=r[7],
            )
            for r in rows
        ]

    async def fetch_contradictions_for_entity(
        self,
        entity_id: UUID,
        *,
        claim_type: str | None = None,
        top_k: int = 20,
    ) -> list[ContradictionData]:
        """Return active contradiction links where the entity is the subject.

        Joins ``relation_contradiction_links`` → ``claims`` (both sides) to
        produce a two-sided contradiction view.
        Side A = the subject claim referenced by ``rcl.relation_evidence_id``.
        Side B = the opposing existing claim (``rcl.claim_id``).

        COLUMN-NAMING DEBT (2026-06-16 data-pipeline-gaps Gap 1):
        ``relation_contradiction_links.relation_evidence_id`` is named like a
        ``relation_evidence_raw.raw_id`` FK but actually stores the subject
        ``claims.claim_id`` written by contradiction_batch.py:99 (no FK
        constraint → mismatch silently accepted; 7180/7180 links match
        ``claims.claim_id``, 0/7180 match ``relation_evidence_raw.raw_id``).
        The previous query joined ``rer.raw_id = rcl.relation_evidence_id`` and
        therefore returned NOTHING for every entity. We join ``claims`` directly
        on the value actually stored, matching the write path.

        BP-069 / API-008: The original query used
          ``AND (:claim_type IS NULL OR rcl.contradiction_type = :claim_type)``
        with ``"claim_type": None`` in the params dict.  asyncpg cannot infer the
        PostgreSQL type of a Python ``None`` value used inside a column equality
        comparison (``rcl.contradiction_type = :claim_type``), raising
        ``AmbiguousParameterError`` on every request where ``claim_type`` was
        absent.  Fix: build the WHERE clause conditionally and never bind a
        ``None``-valued parameter that appears in an equality expression.
        """
        # Build WHERE clause dynamically — only add :claim_type when it is
        # supplied so asyncpg always receives a typed string value.
        conditions = [
            "ca.subject_entity_id = :entity_id",
            "rcl.invalidated_at IS NULL",
        ]
        params: dict[str, object] = {"entity_id": str(entity_id), "top_k": top_k}
        if claim_type is not None:
            conditions.append("rcl.contradiction_type = :claim_type")
            params["claim_type"] = claim_type

        where_clause = "\n  AND ".join(conditions)
        query = f"""
SELECT rcl.link_id,
       rcl.contradiction_type AS claim_type,
       rcl.strength,
       rcl.detected_at,
       -- Side A: new evidence claim (nullable)
       ca.polarity              AS side_a_polarity,
       ca.extraction_confidence AS side_a_confidence,
       ca.doc_id                AS side_a_doc_id,
       ca.claim_text            AS side_a_claim_text,
       ca.created_at            AS side_a_date,
       -- Side B: opposing existing claim
       cb.polarity              AS side_b_polarity,
       cb.extraction_confidence AS side_b_confidence,
       cb.doc_id                AS side_b_doc_id,
       cb.claim_text            AS side_b_claim_text,
       cb.created_at            AS side_b_date
FROM relation_contradiction_links rcl
-- Side A = the subject claim; rcl.relation_evidence_id holds its claim_id
-- (LEFT JOIN keeps a row even on the rare chance the subject claim was deleted).
LEFT JOIN claims ca ON ca.claim_id = rcl.relation_evidence_id
JOIN claims cb ON cb.claim_id = rcl.claim_id
WHERE {where_clause}
ORDER BY rcl.strength DESC
LIMIT :top_k
"""
        result = await self._session.execute(text(query), params)
        rows = result.fetchall()
        out: list[ContradictionData] = []
        for r in rows:
            sides: list[ContradictionSideData] = []
            # Side A (may be absent if evidence has no linked claim)
            if r[4] is not None:
                sides.append(
                    ContradictionSideData(
                        polarity=str(r[4]),
                        confidence=float(r[5]),
                        doc_id=UUID(str(r[6])) if r[6] else None,
                        claim_text=str(r[7]),
                        evidence_date=r[8],
                    ),
                )
            # Side B (always present — inner join)
            sides.append(
                ContradictionSideData(
                    polarity=str(r[9]),
                    confidence=float(r[10]),
                    doc_id=UUID(str(r[11])) if r[11] else None,
                    claim_text=str(r[12]),
                    evidence_date=r[13],
                ),
            )
            out.append(
                ContradictionData(
                    link_id=UUID(str(r[0])),
                    claim_type=str(r[1]),
                    strength=float(r[2]),
                    detected_at=r[3],
                    sides=sides,
                ),
            )
        return out
