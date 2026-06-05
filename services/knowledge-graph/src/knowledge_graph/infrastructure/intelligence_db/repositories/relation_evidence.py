"""RelationEvidence repository — append-only inserts.

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Critical constraints:
- ``partition_key`` is a STORED generated column in ``relation_evidence_raw``
  (``abs(hashtext(subject_entity_id::text)) % 8``).  NEVER include in INSERT.
- ``relation_evidence`` is RANGE-partitioned by month (immutable after insert).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import RelationEvidenceRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RelationEvidenceRepository(RelationEvidenceRepositoryPort):
    """Append-only repository for evidence tables.

    Writes to ``relation_evidence_raw`` (staging) during the hot path.
    The aggregation worker (Worker 13A) later promotes rows to
    ``relation_evidence`` (immutable monthly partitions).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_raw(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        source_document_id: UUID,
        extraction_confidence: float,
        source_trust_weight: float,
        evidence_date: datetime,
        *,
        canonical_type: str | None = None,
        polarity: str = "positive",
        claim_id: UUID | None = None,
        chunk_id: UUID | None = None,
        is_backfill: bool = False,
        entity_provisional: bool = False,
        provisional_queue_id: UUID | None = None,
        evidence_text: str | None = None,
        source_name: str | None = None,
        source_type: str | None = None,
    ) -> UUID:
        """Insert a row into ``relation_evidence_raw`` (hot-path staging).

        IMPORTANT: ``partition_key`` is STORED — not included in INSERT.

        T-B-03: ``source_name`` and ``source_type`` are NULL-safe new columns
        added by migration MIG-EVIDENCE-SOURCE (Wave A T-A-05).  Both default to
        NULL when not provided.

        PLAN-0093 B-3 T-B-3-02: ``claim_id`` and ``chunk_id`` are NOT NULL in
        the ``relation_evidence_raw`` schema (migration 0028). Surface the
        constraint at the writer so callers get a fast ``ValueError`` instead
        of an opaque IntegrityError at commit time.
        """
        if claim_id is None:
            raise ValueError("claim_id is NOT NULL on relation_evidence_raw (PLAN-0093 B-3)")
        if chunk_id is None:
            raise ValueError("chunk_id is NOT NULL on relation_evidence_raw (PLAN-0093 B-3)")
        result = await self._session.execute(
            text("""
INSERT INTO relation_evidence_raw (
    subject_entity_id, object_entity_id, canonical_type, polarity,
    claim_id, chunk_id, source_document_id,
    extraction_confidence, source_trust_weight,
    evidence_date, is_backfill, entity_provisional, provisional_queue_id,
    evidence_text, source_name, source_type
) VALUES (
    :subject_entity_id, :object_entity_id, :canonical_type, :polarity,
    :claim_id, :chunk_id, :source_document_id,
    :extraction_confidence, :source_trust_weight,
    :evidence_date, :is_backfill, :entity_provisional, :provisional_queue_id,
    :evidence_text, :source_name, :source_type
)
RETURNING raw_id
"""),
            {
                "subject_entity_id": str(subject_entity_id),
                "object_entity_id": str(object_entity_id),
                "canonical_type": canonical_type,
                "polarity": polarity,
                "claim_id": str(claim_id) if claim_id else None,
                "chunk_id": str(chunk_id) if chunk_id else None,
                "source_document_id": str(source_document_id),
                "extraction_confidence": extraction_confidence,
                "source_trust_weight": source_trust_weight,
                "evidence_date": evidence_date,
                "is_backfill": is_backfill,
                "entity_provisional": entity_provisional,
                "provisional_queue_id": str(provisional_queue_id) if provisional_queue_id else None,
                "evidence_text": evidence_text,
                "source_name": source_name,
                "source_type": source_type,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    # D-INIT-6 (2026-05-09): the previous ``lookup_source_metadata`` method that
    # used to live here was an R7 cross-service-DB violation — it queried the
    # ``document_source_metadata`` table from this repository's session, but that
    # table only exists in ``nlp_db`` (we run on ``intelligence_db``). Every
    # invocation raised asyncpg ``UndefinedTableError`` and silently dropped
    # source provenance for every enriched event, leaving the intelligence layer
    # producing zero narratives. The clean fix is to propagate ``source_name``
    # in the ``nlp.article.enriched.v1`` event payload itself (see the matching
    # producer-side change in ``services/nlp-pipeline``). The KG consumer now
    # reads ``value.get("source_name")`` directly and never falls back to a
    # cross-DB query.

    async def insert_immutable(
        self,
        relation_id: UUID,
        doc_id: UUID,
        extraction_confidence: float,
        source_weight: float,
        evidence_date: datetime,
        *,
        chunk_id: UUID | None = None,
        evidence_text: str | None = None,
        canonicalized_evidence_text: str | None = None,
        claim_id: UUID | None = None,
    ) -> UUID:
        """Insert a row into ``relation_evidence`` (immutable monthly partition)."""
        result = await self._session.execute(
            text("""
INSERT INTO relation_evidence (
    relation_id, doc_id, chunk_id, evidence_text,
    canonicalized_evidence_text, extraction_confidence,
    source_weight, evidence_date, claim_id
) VALUES (
    :relation_id, :doc_id, :chunk_id, :evidence_text,
    :canonicalized_evidence_text, :extraction_confidence,
    :source_weight, :evidence_date, :claim_id
)
RETURNING evidence_id
"""),
            {
                "relation_id": str(relation_id),
                "doc_id": str(doc_id),
                "chunk_id": str(chunk_id) if chunk_id else None,
                "evidence_text": evidence_text,
                "canonicalized_evidence_text": canonicalized_evidence_text,
                "extraction_confidence": extraction_confidence,
                "source_weight": source_weight,
                "evidence_date": evidence_date,
                "claim_id": str(claim_id) if claim_id else None,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    async def fetch_unprocessed_by_partition(
        self,
        partition_key: int,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        """Fetch unprocessed raw evidence rows for a given partition (Worker 13A)."""
        result = await self._session.execute(
            text("""
SELECT raw_id, subject_entity_id, object_entity_id, canonical_type,
       extraction_confidence, source_trust_weight, evidence_date, is_backfill,
       evidence_text
FROM relation_evidence_raw
WHERE partition_key      = :partition_key
  AND processed          = false
  AND entity_provisional = false
ORDER BY extracted_at
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
            {"partition_key": partition_key, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "raw_id": UUID(str(r[0])),
                "subject_entity_id": UUID(str(r[1])),
                "object_entity_id": UUID(str(r[2])),
                "canonical_type": r[3],
                "extraction_confidence": float(r[4]),
                "source_trust_weight": float(r[5]),
                "evidence_date": r[6],
                "is_backfill": bool(r[7]),
                "evidence_text": r[8],
            }
            for r in rows
        ]

    async def get_all_raw_for_triple(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        canonical_type: str,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        """Fetch all (processed + unprocessed) raw evidence rows for a relation triple."""
        result = await self._session.execute(
            text("""
SELECT raw_id, extraction_confidence, source_trust_weight,
       evidence_date, is_backfill, source_document_id, evidence_text
FROM relation_evidence_raw
WHERE subject_entity_id = :subject
  AND object_entity_id  = :object
  AND canonical_type    = :ctype
  AND entity_provisional = false
ORDER BY evidence_date DESC
LIMIT :limit
"""),
            {
                "subject": str(subject_entity_id),
                "object": str(object_entity_id),
                "ctype": canonical_type,
                "limit": limit,
            },
        )
        rows = result.fetchall()
        return [
            {
                "raw_id": UUID(str(r[0])),
                "extraction_confidence": float(r[1]),
                "source_trust_weight": float(r[2]),
                "evidence_date": r[3],
                "is_backfill": bool(r[4]),
                "source_document_id": UUID(str(r[5])),
                "evidence_text": r[6],
            }
            for r in rows
        ]

    async def get_raw_for_relation_id(
        self,
        relation_id: UUID,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Fetch raw evidence rows for a relation identified by its UUID.

        Resolves the triple (subject, object, canonical_type) from the
        ``relations`` table and queries ``relation_evidence_raw`` using it.
        Used by SummaryWorker (13C) since ``relation_evidence`` (the immutable
        partition table) may be empty if the promotion step has not run.

        Orders by ``source_trust_weight DESC, evidence_date DESC`` to match the
        priority order used by ``get_all_for_relation``.
        """
        result = await self._session.execute(
            text("""
SELECT rer.raw_id, rer.extraction_confidence, rer.source_trust_weight,
       rer.evidence_date, rer.is_backfill, rer.source_document_id,
       rer.evidence_text
FROM relation_evidence_raw rer
JOIN relations r
  ON  r.subject_entity_id = rer.subject_entity_id
  AND r.object_entity_id  = rer.object_entity_id
  AND r.canonical_type    = rer.canonical_type
WHERE r.relation_id          = :relation_id
  AND rer.entity_provisional = false
ORDER BY rer.source_trust_weight DESC, rer.evidence_date DESC
LIMIT :limit
"""),
            {"relation_id": str(relation_id), "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "raw_id": UUID(str(r[0])),
                "extraction_confidence": float(r[1]),
                "source_trust_weight": float(r[2]),
                "evidence_date": r[3],
                "is_backfill": bool(r[4]),
                "source_document_id": UUID(str(r[5])),
                "evidence_text": r[6],
            }
            for r in rows
        ]

    async def get_all_for_relation(
        self,
        relation_id: UUID,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Fetch immutable evidence rows for a given relation (Worker 13C summary).

        Orders by ``source_weight DESC, evidence_date DESC`` to surface the
        highest-quality, most-recent evidence first.

        Note: ``relation_evidence`` has a composite PK ``(evidence_id, evidence_date)``
        due to RANGE partitioning.  This query uses ``idx_rel_evidence_relation``
        which includes ``evidence_date``, enabling partition pruning.
        """
        result = await self._session.execute(
            text("""
SELECT evidence_id, relation_id, doc_id, chunk_id,
       evidence_text, canonicalized_evidence_text,
       extraction_confidence, source_weight, evidence_date,
       claim_id, created_at
FROM relation_evidence
WHERE relation_id = :relation_id
ORDER BY source_weight DESC, evidence_date DESC
LIMIT :limit
"""),
            {"relation_id": str(relation_id), "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "evidence_id": UUID(str(r[0])),
                "relation_id": UUID(str(r[1])),
                "doc_id": UUID(str(r[2])),
                "chunk_id": UUID(str(r[3])) if r[3] else None,
                "evidence_text": r[4],
                "canonicalized_evidence_text": r[5],
                "extraction_confidence": float(r[6]),
                "source_weight": float(r[7]),
                "evidence_date": r[8],
                "claim_id": UUID(str(r[9])) if r[9] else None,
                "created_at": r[10],
            }
            for r in rows
        ]

    async def get_evidence_snippets_batch(
        self,
        relation_ids: list[UUID],
        limit_per_relation: int = 3,
    ) -> dict[UUID, list[str]]:
        """Return top-N evidence snippets per relation in a single CTE query (no N+1).

        Reads from relation_evidence_raw (evidence_text column, added in migration 0019).
        Ordered by extraction_confidence DESC NULLS LAST, evidence_date DESC NULLS LAST.
        JOINs to relations to resolve relation_id (raw table stores the triple, not relation_id).
        # TODO(PRD-0074): upgrade to denormalized top_evidence_snippets JSONB on relations
        """
        if not relation_ids:
            return {}

        result = await self._session.execute(
            text("""
WITH ranked AS (
    SELECT r.relation_id,
           rer.evidence_text AS snip,
           ROW_NUMBER() OVER (
               PARTITION BY r.relation_id
               ORDER BY rer.extraction_confidence DESC NULLS LAST,
                        rer.evidence_date          DESC NULLS LAST
           ) AS rn
    FROM relation_evidence_raw rer
    JOIN relations r
      ON  r.subject_entity_id = rer.subject_entity_id
     AND  r.object_entity_id  = rer.object_entity_id
     AND  r.canonical_type    = rer.canonical_type
    WHERE r.relation_id = ANY(CAST(:relation_ids AS uuid[]))
      AND rer.entity_provisional = false
      AND rer.evidence_text      IS NOT NULL
)
SELECT relation_id, snip
FROM   ranked
WHERE  rn <= :limit
ORDER  BY relation_id, rn
"""),
            {
                "relation_ids": [str(rid) for rid in relation_ids],
                "limit": limit_per_relation,
            },
        )
        rows = result.fetchall()
        out: dict[UUID, list[str]] = {}
        for row in rows:
            rid = UUID(str(row[0]))
            out.setdefault(rid, []).append(str(row[1]))
        return out

    async def get_earliest_evidence_date(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        canonical_type: str,
    ) -> datetime | None:
        """Return the earliest evidence_date for a triple (T-B-01 valid_from source).

        Only considers rows that have been processed (processed=true) to avoid
        using evidence that has not yet been verified by the confidence worker.
        Returns None when no processed evidence exists for the triple.
        """
        result = await self._session.execute(
            text("""
SELECT MIN(evidence_date)
FROM relation_evidence_raw
WHERE subject_entity_id = :subject
  AND object_entity_id  = :object
  AND canonical_type    = :ctype
  AND processed         = true
"""),
            {
                "subject": str(subject_entity_id),
                "object": str(object_entity_id),
                "ctype": canonical_type,
            },
        )
        row = result.fetchone()
        if row is None or row[0] is None:
            return None
        return row[0]  # type: ignore[return-value, no-any-return]

    async def mark_processed(self, raw_ids: list[UUID], processed_at: datetime) -> None:
        """Mark a batch of raw evidence rows as processed."""
        if not raw_ids:
            return
        await self._session.execute(
            text("""
UPDATE relation_evidence_raw
SET processed = true, processed_at = :processed_at
WHERE raw_id = ANY(CAST(:raw_ids AS uuid[]))
"""),
            {
                "raw_ids": [str(rid) for rid in raw_ids],
                "processed_at": processed_at,
            },
        )
