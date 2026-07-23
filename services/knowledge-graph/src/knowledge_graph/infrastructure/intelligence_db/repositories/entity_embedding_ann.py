"""pgvector ANN repository for entity_embedding_state (PRD-0017 §6.5).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

The query uses the pgvector cosine-distance operator ``<=>`` which requires
a HNSW or IVFFlat index for efficient ANN traversal.  The partial HNSW index
on ``fundamentals_ohlcv`` view was created in intelligence-migrations 0001.

Distance semantics: 0 = identical, 2 = maximally dissimilar (opposite).

Partial-index matching (postgres-OOM root cause, 2026-07-22)
-----------------------------------------------------------
The HNSW indexes on this table are **partial**, one per view_type::

    CREATE INDEX idx_entity_emb_definition_hnsw ... USING hnsw (embedding ...)
        WHERE view_type = 'definition' AND embedding IS NOT NULL

Postgres uses a partial index only when its predicate is *provably implied*
by the query's WHERE clause, and that proof is done against **constant
literals** — a bound parameter (``view_type = :view_type``) is opaque to the
planner, so the partial index is skipped and the query degrades to a
``Parallel Seq Scan + Sort`` over the whole table.  Each such scan spikes
``work_mem`` for the sort; ~30 concurrent direct backends multiplied that
into a >6Gi resident-set spike → recurring postgres OOM.

Fix: ``view_type`` is a small, trusted, internal enum — we validate it
against :data:`_VALID_VIEW_TYPES` (exactly the set with partial indexes) and
inline it as a SQL literal so the planner can match the partial HNSW index
(Index Scan, no full-table Sort, no work_mem spike).  Inlining is safe *only*
because the value is allow-listed; it is never interpolated from user input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import AnnResult, EntityEmbeddingANNRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# view_type values that have a matching partial HNSW index in
# intelligence-migrations 0001.  Keep in lock-step with the migration; a value
# outside this set has no index and must not be inlined into the SQL.
_VALID_VIEW_TYPES = frozenset({"definition", "narrative", "fundamentals_ohlcv"})


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
        # Inline view_type as a SQL literal (not a bind param) so the planner
        # can match the partial HNSW index (see module docstring).  Guard with
        # an allow-list first — this is what makes literal interpolation safe.
        if view_type not in _VALID_VIEW_TYPES:
            msg = f"Unknown view_type {view_type!r}; expected one of {sorted(_VALID_VIEW_TYPES)}"
            raise ValueError(msg)

        params: dict[str, object] = {
            "query_embedding": str(query_embedding),
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

        # ``view_type`` is safe to inline — validated against _VALID_VIEW_TYPES
        # above.  A literal ('definition') lets postgres prove the partial-index
        # predicate; a bind param (:view_type) does not (see module docstring).
        stmt = text(f"""
SELECT ees.entity_id,
       (ees.embedding::vector <=> CAST(:query_embedding AS vector)) AS distance
FROM entity_embedding_state ees
JOIN canonical_entities ce ON ce.entity_id = ees.entity_id
WHERE ees.view_type = '{view_type}'
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
