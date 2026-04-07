"""pgvector ANN repository for entity_embedding_state (PRD-0017 §6.5).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

The query uses the pgvector cosine-distance operator ``<=>`` which requires
a HNSW or IVFFlat index for efficient ANN traversal.  The partial HNSW index
on ``fundamentals_ohlcv`` view was created in intelligence-migrations 0001.

Distance semantics: 0 = identical, 2 = maximally dissimilar (opposite).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import AnnResult, EntityEmbeddingANNRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlalchemyEntityEmbeddingANNRepository(EntityEmbeddingANNRepositoryPort):
    """pgvector ANN read repository backed by a SQLAlchemy async session.

    Implements ``find_nearest`` using the ``<=>`` cosine distance operator,
    with an optional JOIN on ``canonical_entities`` for entity-type filtering.

    The session should be bound to the **read-only** replica (R27) when used
    from ``FindSimilarEntitiesUseCase``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_nearest(
        self,
        query_embedding: list[float],
        view_type: str,
        limit: int = 40,
        exclude_entity_id: UUID | None = None,
        entity_types: list[str] | None = None,
    ) -> list[AnnResult]:
        """Return the nearest neighbours by cosine distance (ascending).

        Filters:
        - ``view_type`` — restricts to a single embedding projection
        - ``exclude_entity_id`` — omits the query entity from results
        - ``entity_types`` — restricts via JOIN on ``canonical_entities``
        - Only rows with a non-NULL embedding are considered
        """
        params: dict[str, object] = {
            "query_embedding": str(query_embedding),
            "view_type": view_type,
            "limit": limit,
        }

        # Build optional WHERE clauses (no f-string interpolation for user data)
        extra_conditions = "AND ees.embedding IS NOT NULL\n"

        if exclude_entity_id is not None:
            extra_conditions += "  AND ees.entity_id != :exclude_entity_id\n"
            params["exclude_entity_id"] = str(exclude_entity_id)

        if entity_types:
            # entity_types is a list of trusted internal strings (no user input)
            # Use PostgreSQL ANY(:array) to avoid N query parameters
            extra_conditions += "  AND ce.entity_type = ANY(:entity_types)\n"
            params["entity_types"] = entity_types

        stmt = text(f"""
SELECT ees.entity_id,
       (ees.embedding::vector <=> :query_embedding::vector) AS distance
FROM entity_embedding_state ees
JOIN canonical_entities ce ON ce.entity_id = ees.entity_id
WHERE ees.view_type = :view_type
  {extra_conditions}
ORDER BY distance ASC
LIMIT :limit
""")

        result = await self._session.execute(stmt, params)
        rows = result.fetchall()
        return [AnnResult(entity_id=UUID(str(row[0])), distance=float(row[1])) for row in rows]

    async def get_embedding(
        self,
        entity_id: UUID,
        view_type: str,
    ) -> list[float] | None:
        """Fetch the stored embedding vector for (entity_id, view_type), or None.

        Returns None when the row does not exist or the ``embedding`` column is NULL.
        """
        result = await self._session.execute(
            text("""
SELECT embedding::text
FROM entity_embedding_state
WHERE entity_id = :entity_id
  AND view_type = :view_type
"""),
            {"entity_id": str(entity_id), "view_type": view_type},
        )
        row = result.fetchone()
        if row is None or row[0] is None:
            return None
        # pgvector returns the vector as a string like "[0.1,0.2,...]"
        raw: str = row[0]
        return [float(x) for x in raw.strip("[]").split(",")]
