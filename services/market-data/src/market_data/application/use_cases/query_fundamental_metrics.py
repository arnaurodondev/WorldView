"""Fundamental metrics query use cases (timeseries, screening, available metrics)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
    from market_data.application.ports.uow import UnitOfWork


class GetFundamentalMetricsTimeseriesUseCase:
    """Return timeseries data for a single instrument and metric."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: str,
        metric: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period_type: str | None = None,
        limit: int = 1000,
    ) -> list[MetricDataPoint]:
        return await self._uow.fundamental_metrics_query.get_timeseries(
            instrument_id,
            metric,
            start_date=start_date,
            end_date=end_date,
            period_type=period_type,
            limit=limit,
        )


class ScreenInstrumentsUseCase:
    """Screen instruments by metric thresholds."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        filters: list[ScreenFilter],
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScreenResult]:
        return await self._uow.fundamental_metrics_query.screen(
            filters,
            limit=limit,
            offset=offset,
        )


class GetAvailableFundamentalMetricsUseCase:
    """Return all metric names available for an instrument."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> list[str]:
        return await self._uow.fundamental_metrics_query.get_available_metrics(instrument_id)
