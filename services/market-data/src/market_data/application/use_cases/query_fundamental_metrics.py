"""Fundamental metrics query use cases (timeseries, screening, available metrics)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from market_data.application.ports.cache import ScreenFieldsCachePort
    from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
    from market_data.application.ports.uow import ReadOnlyUnitOfWork
    from market_data.domain.entities import ScreenFieldMetadata


class GetFundamentalMetricsTimeseriesUseCase:
    """Return timeseries data for a single instrument and metric."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
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

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        filters: list[ScreenFilter],
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str | None = None,
        sort_order: str = "asc",
    ) -> tuple[list[ScreenResult], int]:
        return await self._uow.fundamental_metrics_query.screen(
            filters,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )


class GetAvailableFundamentalMetricsUseCase:
    """Return all metric names available for an instrument."""

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(self, instrument_id: str) -> list[str]:
        return await self._uow.fundamental_metrics_query.get_available_metrics(instrument_id)


class ScreenFieldsMetadataUseCase:
    """Return screenable field metadata: Valkey cache first, DB fallback (PRD-0017 §6.2).

    On a cache miss the use case reads from the ``screen_field_metadata`` table
    via the read-replica session and warms the cache for subsequent requests.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork, cache: ScreenFieldsCachePort) -> None:
        self._uow = uow
        self._cache = cache

    async def execute(self) -> list[ScreenFieldMetadata]:
        # 1. Try Valkey (fast path)
        cached = await self._cache.get_all()
        if cached is not None:
            return cached

        # 2. DB fallback (slow path — read replica via UoW, R27)
        fields = await self._uow.fundamental_metrics_query.get_screen_field_metadata()

        # 3. Warm cache for subsequent requests
        if fields:
            await self._cache.set_all(fields)

        return fields
