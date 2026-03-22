"""PostgreSQL adapter for fundamental_metrics read-optimized table.

Write-side: bulk upsert metric rows extracted from fundamentals records.
Uses ON CONFLICT (instrument_id, as_of_date, metric, period_type) DO UPDATE
for idempotent last-write-wins semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert

from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from market_data.infrastructure.db.metric_extractor import MetricRow


class PgFundamentalMetricsRepository:
    """SQLAlchemy-backed repository for fundamental_metrics upserts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_metrics(self, rows: list[MetricRow]) -> None:
        """Bulk-upsert metric rows into fundamental_metrics.

        Uses PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` on the unique
        constraint ``(instrument_id, as_of_date, metric, period_type)`` so
        that re-ingestion overwrites the same row (idempotent).
        """
        if not rows:
            return

        for row in rows:
            stmt = insert(FundamentalMetricModel).values(
                instrument_id=row.instrument_id,
                as_of_date=row.as_of_date,
                metric=row.metric,
                value_numeric=row.value_numeric,
                value_text=row.value_text,
                period_type=row.period_type,
                section=row.section,
                ingested_at=row.ingested_at,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_fundamental_metrics_instrument_date_metric",
                set_={
                    "value_numeric": stmt.excluded.value_numeric,
                    "value_text": stmt.excluded.value_text,
                    "section": stmt.excluded.section,
                    "ingested_at": stmt.excluded.ingested_at,
                },
            )
            await self._session.execute(stmt)
