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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RelationEvidenceRepository:
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
    ) -> UUID:
        """Insert a row into ``relation_evidence_raw`` (hot-path staging).

        IMPORTANT: ``partition_key`` is STORED — not included in INSERT.
        """
        result = await self._session.execute(
            text("""
INSERT INTO relation_evidence_raw (
    subject_entity_id, object_entity_id, canonical_type, polarity,
    claim_id, chunk_id, source_document_id,
    extraction_confidence, source_trust_weight,
    evidence_date, is_backfill, entity_provisional, provisional_queue_id
) VALUES (
    :subject_entity_id, :object_entity_id, :canonical_type, :polarity,
    :claim_id, :chunk_id, :source_document_id,
    :extraction_confidence, :source_trust_weight,
    :evidence_date, :is_backfill, :entity_provisional, :provisional_queue_id
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
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

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
       extraction_confidence, source_trust_weight, evidence_date, is_backfill
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
       evidence_date, is_backfill, source_document_id
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

    async def mark_processed(self, raw_ids: list[UUID], processed_at: datetime) -> None:
        """Mark a batch of raw evidence rows as processed."""
        if not raw_ids:
            return
        await self._session.execute(
            text("""
UPDATE relation_evidence_raw
SET processed = true, processed_at = :processed_at
WHERE raw_id = ANY(:raw_ids)
"""),
            {
                "raw_ids": [str(rid) for rid in raw_ids],
                "processed_at": processed_at,
            },
        )
