"""IntelligenceAggregatesRepository — raw-SQL read-only queries for entity intelligence.

Provides the aggregated data needed by GetEntityIntelligenceUseCase:
  - Confidence breakdown (AVG support/corroboration/contradiction, evidence recency)
  - Source distribution (top-10 source_type/source_name shares)
  - 90-day confidence trend series

S7 does not own intelligence_db DDL — all schema changes live in intelligence-migrations.
Read-only: always bound to the read-replica session (R27).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class IntelligenceAggregatesRepository:
    """Read-only aggregation queries for entity intelligence endpoints.

    Args:
        session: A read-only AsyncSession (from ReadOnlyDbSessionDep, R27).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_confidence_breakdown(
        self,
        entity_id: UUID,
    ) -> dict[str, Any]:
        """Return AVG confidence components and latest_evidence_at for an entity.

        Aggregates across all active (valid_to IS NULL) relations where the entity
        appears as subject or object.  Extracts JSON paths from confidence_components.

        Returns dict with keys:
            mean_support, mean_corroboration, mean_contradiction,
            latest_evidence_at, relation_count
        """
        result = await self._session.execute(
            text("""
SELECT
    AVG((confidence_components->>'support')::float)      AS mean_support,
    AVG((confidence_components->>'corroboration')::float) AS mean_corroboration,
    AVG((confidence_components->>'contradiction')::float) AS mean_contradiction,
    MAX(latest_evidence_at)                               AS latest_evidence_at,
    COUNT(*)                                              AS relation_count
FROM relations
WHERE (subject_entity_id = CAST(:entity_id AS uuid)
       OR object_entity_id = CAST(:entity_id AS uuid))
  AND valid_to IS NULL
"""),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        if row is None:
            return {
                "mean_support": None,
                "mean_corroboration": None,
                "mean_contradiction": None,
                "latest_evidence_at": None,
                "relation_count": 0,
            }
        return {
            "mean_support": float(row[0]) if row[0] is not None else None,
            "mean_corroboration": float(row[1]) if row[1] is not None else None,
            "mean_contradiction": float(row[2]) if row[2] is not None else None,
            "latest_evidence_at": row[3],
            "relation_count": int(row[4]) if row[4] is not None else 0,
        }

    async def get_source_distribution(
        self,
        entity_id: UUID,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the top-N source_type/source_name distribution for an entity.

        Queries relation_evidence_raw for all evidence linked to relations where
        entity_id is subject or object.  Computes percentage share per source pair.

        Returns list of dicts with keys:
            source_type, source_name, count, pct
        """
        # BUG FIX (DP-PLAN-0074-02): relation_evidence_raw has no relation_id column.
        # The table stores the raw triple (subject_entity_id, object_entity_id,
        # canonical_type) and is joined to relations on those three columns.
        result = await self._session.execute(
            text("""
WITH evidence_sources AS (
    SELECT rer.source_type, rer.source_name, COUNT(*) AS cnt
    FROM relation_evidence_raw rer
    JOIN relations r
      ON  r.subject_entity_id = rer.subject_entity_id
      AND r.object_entity_id  = rer.object_entity_id
      AND r.canonical_type    = rer.canonical_type
    WHERE (r.subject_entity_id = CAST(:entity_id AS uuid)
           OR r.object_entity_id = CAST(:entity_id AS uuid))
      AND r.valid_to IS NULL
    GROUP BY rer.source_type, rer.source_name
    ORDER BY cnt DESC
    LIMIT :limit
),
total AS (
    SELECT SUM(cnt) AS grand_total FROM evidence_sources
)
SELECT
    es.source_type,
    es.source_name,
    es.cnt::int AS count,
    CASE WHEN t.grand_total > 0
         THEN ROUND((es.cnt::float / t.grand_total::float)::numeric, 4)::float
         ELSE 0.0
    END AS pct
FROM evidence_sources es, total t
ORDER BY es.cnt DESC
"""),
            {"entity_id": str(entity_id), "limit": limit},
        )
        return [
            {
                "source_type": row[0],
                "source_name": row[1],
                "count": int(row[2]),
                "pct": float(row[3]),
            }
            for row in result.fetchall()
        ]

    async def get_confidence_trend(
        self,
        entity_id: UUID,
        days: int = 90,
    ) -> list[dict[str, Any]]:
        """Return a daily confidence trend over the last *days* days.

        Aggregates AVG(confidence_score) per day from relation_evidence_raw,
        filtered to evidence linked to relations touching entity_id.

        Returns list of dicts with keys:
            date (datetime.date), avg_confidence (float)
        """
        result = await self._session.execute(
            text("""
SELECT
    date_trunc('day', evidence_date)::date AS d,
    AVG(confidence_score)::float           AS avg_confidence
FROM relation_evidence_raw
WHERE relation_id IN (
    SELECT relation_id
    FROM relations
    WHERE (subject_entity_id = CAST(:entity_id AS uuid)
           OR object_entity_id = CAST(:entity_id AS uuid))
      AND valid_to IS NULL
)
  AND evidence_date >= NOW() - INTERVAL '1 day' * :days
GROUP BY d
ORDER BY d
"""),
            {"entity_id": str(entity_id), "days": days},
        )
        rows = result.fetchall()
        trend: list[dict[str, Any]] = []
        for row in rows:
            raw_date = row[0]
            # asyncpg may return a datetime.date or a datetime object depending on cast
            if isinstance(raw_date, datetime):
                point_date: date = raw_date.date()
            else:
                point_date = raw_date  # type: ignore[assignment]
            trend.append({"date": point_date, "avg_confidence": float(row[1]) if row[1] is not None else 0.0})
        return trend
