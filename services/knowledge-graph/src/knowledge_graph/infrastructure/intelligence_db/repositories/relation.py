"""Relation repository — upsert with advisory lock (PRD §6.7 Block 12a).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Critical constraints:
- ``partition_key`` is a STORED generated column — NEVER include in INSERT.
- Upsert is keyed on (subject_entity_id, canonical_type, object_entity_id).
- Advisory lock ``pg_advisory_xact_lock()`` on the triple hash prevents
  concurrent upserts from creating duplicate relation rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class RelationRepository:
    """Read/write repository for ``relations`` (HASH-partitioned x 8)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        subject_entity_id: UUID,
        object_entity_id: UUID,
        canonical_type: str,
        semantic_mode: str,
        decay_class: str,
        decay_alpha: float,
        base_confidence: float,
    ) -> UUID:
        """Upsert a relation, returning the relation_id.

        Acquires an advisory lock on the triple hash before the upsert to
        prevent concurrent inserts from duplicating the relation.

        IMPORTANT: ``partition_key`` is STORED — not included in INSERT.
        """
        # Acquire advisory lock on stable hash of the triple to prevent
        # concurrent upserts on the same (subject, type, object).
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(    hashtext(:subject || :ctype || :object))"),
            {
                "subject": str(subject_entity_id),
                "ctype": canonical_type,
                "object": str(object_entity_id),
            },
        )

        # Upsert: on conflict update evidence metadata, mark confidence stale.
        # partition_key NOT in INSERT — it is GENERATED ALWAYS AS STORED.
        result = await self._session.execute(
            text("""
INSERT INTO relations (
    subject_entity_id, canonical_type, object_entity_id,
    semantic_mode, decay_class, decay_alpha, base_confidence,
    confidence_stale, summary_stale,
    first_evidence_at, latest_evidence_at, evidence_count
) VALUES (
    :subject_entity_id, :canonical_type, :object_entity_id,
    :semantic_mode, :decay_class, :decay_alpha, :base_confidence,
    true, true,
    now(), now(), 1
)
ON CONFLICT (subject_entity_id, canonical_type, object_entity_id) DO UPDATE SET
    latest_evidence_at = now(),
    evidence_count     = relations.evidence_count + 1,
    confidence_stale   = true,
    summary_stale      = true
RETURNING relation_id
"""),
            {
                "subject_entity_id": str(subject_entity_id),
                "canonical_type": canonical_type,
                "object_entity_id": str(object_entity_id),
                "semantic_mode": semantic_mode,
                "decay_class": decay_class,
                "decay_alpha": decay_alpha,
                "base_confidence": base_confidence,
            },
        )
        row = result.fetchone()
        return UUID(str(row[0]))  # type: ignore[index]

    async def get(
        self,
        subject_entity_id: UUID,
        canonical_type: str,
        object_entity_id: UUID,
    ) -> dict[str, object] | None:
        """Fetch a relation by its natural triple key."""
        result = await self._session.execute(
            text("""
SELECT relation_id, semantic_mode, decay_class, decay_alpha, base_confidence,
       confidence, confidence_stale, summary_stale,
       evidence_count, first_evidence_at, latest_evidence_at
FROM relations
WHERE subject_entity_id = :subject
  AND canonical_type    = :ctype
  AND object_entity_id  = :object
"""),
            {
                "subject": str(subject_entity_id),
                "ctype": canonical_type,
                "object": str(object_entity_id),
            },
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "relation_id": UUID(str(row[0])),
            "semantic_mode": row[1],
            "decay_class": row[2],
            "decay_alpha": float(row[3]),
            "base_confidence": float(row[4]),
            "confidence": float(row[5]) if row[5] is not None else None,
            "confidence_stale": bool(row[6]),
            "summary_stale": bool(row[7]),
            "evidence_count": int(row[8]),
            "first_evidence_at": row[9],
            "latest_evidence_at": row[10],
        }

    async def mark_confidence_updated(
        self,
        relation_id: UUID,
        confidence: float,
        computed_at: datetime,
    ) -> None:
        """Mark a relation's confidence as freshly computed."""
        await self._session.execute(
            text("""
UPDATE relations SET
    confidence                  = :confidence,
    confidence_stale            = false,
    confidence_last_computed_at = :computed_at,
    summary_stale               = true
WHERE relation_id = :relation_id
"""),
            {
                "relation_id": str(relation_id),
                "confidence": confidence,
                "computed_at": computed_at,
            },
        )
