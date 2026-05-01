"""RelationTypeRegistry repository — exact-match + ANN search (PRD §6.7 Block 11).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

Block 11 canonicalization is 3-step:
1. Exact match against canonical_type (this repo's ``find_exact``).
2. Soft-map via ANN cosine search on embedding column (this repo's ``find_by_embedding``).
3. No match → propose via outbox (handled by the application block, not here).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RelationTypeRegistryRepository:
    """Read repository for ``relation_type_registry``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_exact(self, candidate_type: str) -> dict[str, object] | None:
        """Step 1: exact-match lookup against canonical_type."""
        result = await self._session.execute(
            text("""
SELECT rtr.type_id, rtr.canonical_type, rtr.semantic_mode, rtr.decay_class, rtr.base_confidence, dcc.decay_alpha
FROM relation_type_registry rtr
JOIN decay_class_config dcc ON dcc.decay_class = rtr.decay_class
WHERE rtr.canonical_type = :canonical_type
  AND rtr.is_active       = true
"""),
            {"canonical_type": candidate_type},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "type_id": row[0],
            "canonical_type": row[1],
            "semantic_mode": row[2],
            "decay_class": row[3],
            "base_confidence": float(row[4]),
            "decay_alpha": float(row[5]),
        }

    async def find_exact_simple(self, candidate_type: str) -> dict[str, object] | None:
        """Step 1: exact-match lookup (simplified — no JOIN, for tests without decay config)."""
        result = await self._session.execute(
            text("""
SELECT type_id, canonical_type, semantic_mode, decay_class, base_confidence
FROM relation_type_registry
WHERE canonical_type = :canonical_type AND is_active = true
"""),
            {"canonical_type": candidate_type},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "type_id": row[0],
            "canonical_type": row[1],
            "semantic_mode": row[2],
            "decay_class": row[3],
            "base_confidence": float(row[4]),
        }

    async def find_by_embedding(
        self,
        query_embedding: list[float],
        distance_threshold: float = 0.35,
        limit: int = 1,
    ) -> dict[str, object] | None:
        """Step 2: soft-map via ANN cosine distance on embedding column.

        Returns the closest type if distance ≤ *distance_threshold*, else None.
        """
        # pgvector cosine distance operator: <=>
        # Smaller value = more similar; threshold is MAX distance allowed.
        result = await self._session.execute(
            text("""
SELECT rtr.type_id, rtr.canonical_type, rtr.semantic_mode, rtr.decay_class, rtr.base_confidence,
             dcc.decay_alpha,
       rtr.embedding <=> CAST(:query_embedding AS vector) AS cosine_distance
FROM relation_type_registry rtr
JOIN decay_class_config dcc ON dcc.decay_class = rtr.decay_class
WHERE rtr.is_active  = true
  AND rtr.embedding IS NOT NULL
ORDER BY cosine_distance
LIMIT :limit
"""),
            {
                "query_embedding": str(query_embedding),
                "limit": limit,
            },
        )
        row = result.fetchone()
        if not row:
            return None
        cosine_distance = float(row[6])
        if cosine_distance > distance_threshold:
            return None
        return {
            "type_id": row[0],
            "canonical_type": row[1],
            "semantic_mode": row[2],
            "decay_class": row[3],
            "base_confidence": float(row[4]),
            "decay_alpha": float(row[5]),
            "cosine_distance": cosine_distance,
        }
