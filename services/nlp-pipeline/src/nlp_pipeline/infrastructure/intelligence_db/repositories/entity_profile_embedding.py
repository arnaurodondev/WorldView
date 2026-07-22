"""EntityProfileEmbedding repository — ANN HNSW search in intelligence_db.

Uses raw SQL (text()) — S6 does not own intelligence_db DDL.

Partial-index matching (postgres-OOM root cause, 2026-07-22)
-----------------------------------------------------------
The HNSW indexes on ``entity_embedding_state`` are **partial**, one per
view_type (``WHERE view_type = 'definition' AND embedding IS NOT NULL`` etc.,
created in intelligence-migrations 0001).  Postgres matches a partial index
only when its predicate is provably implied by the query WHERE clause, and it
proves that against **constant literals** — a bound parameter
(``view_type = :view_type``) is opaque to the planner, so the index is skipped
and the query degrades to a ``Parallel Seq Scan + Sort`` over the whole table.
That sort spikes ``work_mem`` per concurrent backend → recurring postgres OOM.

Fix: validate ``view_type`` against :data:`_VALID_VIEW_TYPES` (the exact set of
partial indexes) and inline it as a SQL literal so the planner uses the partial
HNSW index.  Inlining is safe only because the value is allow-listed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# view_type values that have a matching partial HNSW index in
# intelligence-migrations 0001.  Keep in lock-step with the migration.
_VALID_VIEW_TYPES = frozenset({"definition", "narrative", "fundamentals_ohlcv"})


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
        # Inline view_type as a SQL literal (allow-listed, so safe) rather than a
        # bind param, so postgres can prove the partial-HNSW-index predicate and
        # avoid a full-table Parallel Seq Scan + Sort (see module docstring).
        if view_type not in _VALID_VIEW_TYPES:
            msg = f"Unknown view_type {view_type!r}; expected one of {sorted(_VALID_VIEW_TYPES)}"
            raise ValueError(msg)

        # pgvector cosine distance operator: <=>
        result = await self._session.execute(
            text(
                "SELECT entity_id, embedding <=> cast(:query_vec AS vector) AS distance "
                "FROM entity_embedding_state "
                f"WHERE view_type = '{view_type}' "
                "AND embedding IS NOT NULL "
                "ORDER BY distance ASC "
                "LIMIT :top_k",
            ),
            {
                "query_vec": str(query_embedding),
                "top_k": top_k,
            },
        )
        rows = result.fetchall()
        return [(UUID(str(row[0])), float(row[1])) for row in rows if float(row[1]) <= max_distance]
