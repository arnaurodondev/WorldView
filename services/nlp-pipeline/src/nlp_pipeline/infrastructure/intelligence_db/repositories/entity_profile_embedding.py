"""EntityProfileEmbedding repository — ANN HNSW search in intelligence_db.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class EntityProfileEmbeddingRepository:
    """ANN search against entity_embedding_state (PRD §6.7 Block 9 Stage 4)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ann_search(
        self,
        query_embedding: list[float],
        view_type: str = "definition",
        max_distance: float = 0.35,
        top_k: int = 5,
    ) -> list[tuple[UUID, float]]:
        """Stage 4 — ANN HNSW search against entity_embedding_state.

        Uses the ``definition`` view (stable identity) for resolution — not
        ``narrative``, which would pollute results with temporal context.

        Returns list of (entity_id, cosine_distance) sorted ascending.
        """
        # pgvector cosine distance operator: <=>
        result = await self._session.execute(
            text(
                "SELECT entity_id, embedding <=> :query_vec::vector AS distance "
                "FROM entity_embedding_state "
                "WHERE view_type = :view_type "
                "AND embedding IS NOT NULL "
                "ORDER BY distance ASC "
                "LIMIT :top_k"
            ),
            {
                "query_vec": str(query_embedding),
                "view_type": view_type,
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [(UUID(str(row[0])), float(row[1])) for row in rows if float(row[1]) <= max_distance]
