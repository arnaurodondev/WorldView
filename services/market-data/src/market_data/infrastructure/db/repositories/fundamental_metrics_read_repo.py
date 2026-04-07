"""Read-only fundamental metrics query repository implementation.

Wraps the low-level query helpers in ``fundamental_metrics_query`` to satisfy
the ``FundamentalMetricsQueryRepository`` port.  The API layer depends on the
port, never on the underlying query helpers directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_data.application.ports.repositories import (
    FundamentalMetricsQueryRepository,
    MetricDataPoint,
    ScreenFilter,
    ScreenResult,
)
from market_data.infrastructure.db.repositories.fundamental_metrics_query import (
    query_available_metrics,
    query_screen,
    query_screen_field_metadata,
    query_timeseries,
)

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

    from market_data.domain.entities import ScreenFieldMetadata


class PgFundamentalMetricsQueryRepository(FundamentalMetricsQueryRepository):
    """SQLAlchemy-backed query repository for the fundamental_metrics table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_timeseries(
        self,
        instrument_id: str,
        metric: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period_type: str | None = None,
        limit: int = 1000,
    ) -> list[MetricDataPoint]:
        return await query_timeseries(
            self._session,
            instrument_id=instrument_id,
            metric=metric,
            start_date=start_date,
            end_date=end_date,
            period_type=period_type,
            limit=limit,
        )

    async def screen(
        self,
        filters: list[ScreenFilter],
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> tuple[list[ScreenResult], int]:
        return await query_screen(
            self._session,
            filters=filters,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_available_metrics(self, instrument_id: str) -> list[str]:
        return await query_available_metrics(self._session, instrument_id)

    async def get_screen_field_metadata(self) -> list[ScreenFieldMetadata]:
        return await query_screen_field_metadata(self._session)
