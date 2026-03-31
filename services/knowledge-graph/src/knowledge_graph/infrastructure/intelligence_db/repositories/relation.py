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

    async def fetch_stale_confidence(
        self,
        partition_key: int,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        """Fetch relations with stale confidence for a hash partition (Worker 13A).

        Uses the HASH partition on ``relations`` (8 partitions keyed by
        ``abs(hashtext(subject::text || ctype || object::text)) % 8``).
        Returns rows FOR UPDATE SKIP LOCKED.
        """
        result = await self._session.execute(
            text("""
SELECT relation_id, semantic_mode, decay_class, decay_alpha, base_confidence
FROM relations
WHERE confidence_stale = true
  AND abs(hashtext(subject_entity_id::text || canonical_type || object_entity_id::text)) % 8 = :partition_key
ORDER BY latest_evidence_at DESC
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
            {"partition_key": partition_key, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "relation_id": UUID(str(r[0])),
                "semantic_mode": r[1],
                "decay_class": r[2],
                "decay_alpha": float(r[3]),
                "base_confidence": float(r[4]),
            }
            for r in rows
        ]

    async def fetch_stale_summary(self, limit: int = 50) -> list[dict[str, object]]:
        """Fetch relations needing a fresh LLM summary (Worker 13C)."""
        result = await self._session.execute(
            text("""
SELECT relation_id, semantic_mode, decay_class, decay_alpha, confidence
FROM relations
WHERE summary_stale = true
  AND confidence IS NOT NULL
ORDER BY confidence DESC, latest_evidence_at DESC
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
            {"limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "relation_id": UUID(str(r[0])),
                "semantic_mode": r[1],
                "decay_class": r[2],
                "decay_alpha": float(r[3]),
                "confidence": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]

    async def mark_summary_updated(self, relation_id: UUID) -> None:
        """Clear ``summary_stale`` after a new summary has been generated."""
        await self._session.execute(
            text("UPDATE relations SET summary_stale = false WHERE relation_id = :relation_id"),
            {"relation_id": str(relation_id)},
        )

    async def fetch_stale_summary_embeddings(self, limit: int = 100) -> list[dict[str, object]]:
        """Fetch relation summaries whose embeddings have not been computed (Worker 13F)."""
        result = await self._session.execute(
            text("""
SELECT rs.summary_id, rs.relation_id, rs.summary_text, rs.model_id
FROM relation_summaries rs
WHERE rs.is_current       = true
  AND rs.summary_text     IS NOT NULL
  AND rs.summary_embedding IS NULL
ORDER BY rs.generated_at
LIMIT :limit
"""),
            {"limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "summary_id": UUID(str(r[0])),
                "relation_id": UUID(str(r[1])),
                "summary_text": r[2],
                "model_id": r[3],
            }
            for r in rows
        ]

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

    # ── API query methods ─────────────────────────────────────────────────────

    async def list_for_entity(
        self,
        entity_id: UUID,
        *,
        min_confidence: float = 0.0,
        semantic_mode: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Fetch relations where entity is the subject or object (API: neighbourhood).

        Uses a fully parameterised query — no f-strings, no dynamic SQL construction.
        """
        result = await self._session.execute(
            text("""
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE (r.subject_entity_id = :entity_id OR r.object_entity_id = :entity_id)
  AND (r.confidence IS NULL OR r.confidence >= :min_confidence)
  AND (:semantic_mode IS NULL OR r.semantic_mode = :semantic_mode)
ORDER BY r.latest_evidence_at DESC
LIMIT :limit
"""),
            {
                "entity_id": str(entity_id),
                "min_confidence": min_confidence,
                "semantic_mode": semantic_mode,
                "limit": limit,
            },
        )
        rows = result.fetchall()
        return [
            {
                "relation_id": UUID(str(r[0])),
                "subject_entity_id": UUID(str(r[1])),
                "object_entity_id": UUID(str(r[2])),
                "canonical_type": r[3],
                "semantic_mode": r[4],
                "decay_class": r[5],
                "confidence": float(r[6]) if r[6] is not None else None,
                "confidence_stale": bool(r[7]),
                "evidence_count": int(r[8]),
                "first_evidence_at": r[9],
                "latest_evidence_at": r[10],
            }
            for r in rows
        ]

    async def list_filtered(
        self,
        *,
        subject_entity_id: UUID | None = None,
        object_entity_id: UUID | None = None,
        canonical_type: str | None = None,
        semantic_mode: str | None = None,
        min_confidence: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """Paginated, filtered relation list (API: GET /relations).

        All user-supplied values are bound via named parameters;
        IS NULL checks replace dynamic WHERE clause construction.
        """
        # Build WHERE clauses conditionally to avoid asyncpg type-inference errors
        # when all optional params are None (PostgreSQL can't infer type from NULL alone).
        where_clauses = ["1=1"]
        params: dict[str, object] = {"limit": limit, "offset": offset}

        if subject_entity_id is not None:
            where_clauses.append("r.subject_entity_id = :subject_entity_id")
            params["subject_entity_id"] = str(subject_entity_id)
        if object_entity_id is not None:
            where_clauses.append("r.object_entity_id = :object_entity_id")
            params["object_entity_id"] = str(object_entity_id)
        if canonical_type is not None:
            where_clauses.append("r.canonical_type = :canonical_type")
            params["canonical_type"] = canonical_type
        if semantic_mode is not None:
            where_clauses.append("r.semantic_mode = :semantic_mode")
            params["semantic_mode"] = semantic_mode
        if min_confidence is not None:
            where_clauses.append("(r.confidence IS NULL OR r.confidence >= :min_confidence)")
            params["min_confidence"] = min_confidence

        where_sql = " AND ".join(where_clauses)

        data_result = await self._session.execute(
            text(f"""
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE {where_sql}
ORDER BY r.latest_evidence_at DESC
LIMIT :limit OFFSET :offset
"""),
            params,
        )
        rows = data_result.fetchall()

        count_result = await self._session.execute(
            text(f"SELECT COUNT(*) FROM relations r WHERE {where_sql}"),
            params,
        )
        total = int(count_result.scalar() or 0)

        return (
            [
                {
                    "relation_id": UUID(str(r[0])),
                    "subject_entity_id": UUID(str(r[1])),
                    "object_entity_id": UUID(str(r[2])),
                    "canonical_type": r[3],
                    "semantic_mode": r[4],
                    "decay_class": r[5],
                    "confidence": float(r[6]) if r[6] is not None else None,
                    "confidence_stale": bool(r[7]),
                    "evidence_count": int(r[8]),
                    "first_evidence_at": r[9],
                    "latest_evidence_at": r[10],
                }
                for r in rows
            ],
            total,
        )

    async def get_stats(self) -> dict[str, object]:
        """Return aggregate graph statistics (API: GET /graph/stats)."""
        result = await self._session.execute(
            text("""
SELECT
    (SELECT COUNT(*) FROM canonical_entities)            AS entity_count,
    (SELECT COUNT(*) FROM relations)                     AS relation_count,
    (SELECT COUNT(*) FROM relation_evidence_raw)         AS evidence_count,
    (SELECT COUNT(*) FROM relations WHERE confidence_stale = true)
                                                         AS stale_confidence_count,
    (SELECT COUNT(*) FROM relation_contradiction_links WHERE invalidated_at IS NULL)
                                                         AS contradiction_link_count
"""),
        )
        row = result.fetchone()

        mode_result = await self._session.execute(
            text("SELECT semantic_mode, COUNT(*) FROM relations GROUP BY semantic_mode"),
        )
        relations_by_mode: dict[str, int] = {r[0]: int(r[1]) for r in mode_result.fetchall()}

        return {
            "entity_count": int(row[0]) if row else 0,
            "relation_count": int(row[1]) if row else 0,
            "evidence_count": int(row[2]) if row else 0,
            "stale_confidence_count": int(row[3]) if row else 0,
            "contradiction_link_count": int(row[4]) if row else 0,
            "relations_by_semantic_mode": relations_by_mode,
        }
