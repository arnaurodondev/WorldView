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
        """Return mean confidence + latest_evidence_at + relation_count for an entity.

        Aggregates across all active (valid_to IS NULL) relations where the entity
        appears as subject or object.

        D-R3-001 / D-P1-002 fix (PLAN-0087, 2026-05-09): the relations table has
        NO `confidence_components` JSONB column — PLAN-0074 Wave B designed it
        but never migrated.  Read-side query now uses the scalar `confidence`
        column for `mean_support` so the endpoint stops 500-ing.  The
        corroboration/contradiction averages are returned as None until the
        upstream populator (ConfidenceWorker) ships the JSONB column post-demo.
        The dict shape is preserved for backward compatibility with callers
        (`get_entity_intelligence` use case + `EntityIntelligencePublic`).

        Returns dict with keys:
            mean_support, mean_corroboration, mean_contradiction,
            latest_evidence_at, relation_count
        """
        result = await self._session.execute(
            text("""
SELECT
    AVG(confidence)              AS mean_confidence,
    MAX(latest_evidence_at)      AS latest_evidence_at,
    COUNT(*)                     AS relation_count
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
            # `mean_support` now repurposed to mean overall confidence (the only
            # scalar we have).  Pre-migration field kept for contract stability.
            "mean_support": float(row[0]) if row[0] is not None else None,
            # No JSONB column means we cannot decompose; return None.
            "mean_corroboration": None,
            "mean_contradiction": None,
            "latest_evidence_at": row[1],
            "relation_count": int(row[2]) if row[2] is not None else 0,
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

        SA-4 backfill (2026-05-10): switched source from relation_evidence_raw to
        the partitioned relation_evidence table.  The raw table still stores
        evidence_date = now() at extraction time; the partitioned table has correct
        published_at dates after the backfill_evidence_dates.py run.

        relation_evidence has relation_id directly (unlike raw, which stores the
        triple), so the join is a single FK lookup instead of a triple-join.

        D-R3-001 (PLAN-0087, 2026-05-09): the previous query referenced
        `confidence_score` (does not exist) AND filtered via `relation_id IN
        (SELECT relation_id FROM relations ...)` (relation_evidence_raw has no
        relation_id column — same gotcha as get_source_distribution).
        Both fixed in one go: use `extraction_confidence` (the actual scalar)
        and join on the raw triple (subject_entity_id, object_entity_id,
        canonical_type), matching the existing get_source_distribution shape.
        """
        result = await self._session.execute(
            text("""
WITH evidence_in_window AS (
    -- Use the partitioned relation_evidence table (not raw) so that
    -- evidence_date reflects the document's published_at, not extraction time.
    -- The backfill_evidence_dates.py script set correct dates on all 438 rows.
    SELECT re.evidence_date, re.extraction_confidence
    FROM relation_evidence re
    JOIN relations r ON r.relation_id = re.relation_id
    WHERE (r.subject_entity_id = CAST(:entity_id AS uuid)
           OR r.object_entity_id = CAST(:entity_id AS uuid))
      AND r.valid_to IS NULL
      AND re.evidence_date >= NOW() - INTERVAL '1 day' * :days
)
SELECT
    date_trunc('day', evidence_date)::date AS d,
    AVG(extraction_confidence)::float       AS avg_confidence
FROM evidence_in_window
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
