"""Fundamental metrics API router — timeseries and screening endpoints.

Reads from the ``fundamental_metrics`` read-optimised projection table.
All queries use the **read session** (replica when configured) to avoid
adding load to the write DB.

Existing section-level fundamentals endpoints remain unchanged and continue
to read from the 18 section tables.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import (
    get_available_metrics_uc,
    get_screen_instruments_uc,
    get_timeseries_uc,
)
from market_data.api.schemas.fundamental_metrics import (
    AvailableMetricsResponse,
    MetricDataPointResponse,
    ScreenInstrumentResponse,
    ScreenRequest,
    ScreenResponse,
    TimeseriesResponse,
)
from market_data.application.ports.repositories import ScreenFilter
from market_data.application.use_cases.query_fundamental_metrics import (
    GetAvailableFundamentalMetricsUseCase,
    GetFundamentalMetricsTimeseriesUseCase,
    ScreenInstrumentsUseCase,
)

router = APIRouter(tags=["fundamental-metrics"])


@router.get("/fundamentals/timeseries", response_model=TimeseriesResponse)
async def get_timeseries(
    instrument_id: Annotated[str, Query(description="Instrument UUID")],
    metric: Annotated[str, Query(description="Metric name (e.g. pe_ratio, target_price, revenue)")],
    start_date: Annotated[date | None, Query(description="Start date (inclusive)")] = None,
    end_date: Annotated[date | None, Query(description="End date (inclusive)")] = None,
    period_type: Annotated[str | None, Query(description="Filter by period type (ANNUAL, QUARTERLY, SNAPSHOT)")] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    uc: GetFundamentalMetricsTimeseriesUseCase = Depends(get_timeseries_uc),  # type: ignore[assignment]
) -> TimeseriesResponse:
    """Return timeseries data for a single instrument and metric.

    Query the read-optimised ``fundamental_metrics`` table.
    """
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must not be after end_date",
        )
    data_points = await uc.execute(
        instrument_id,
        metric,
        start_date=start_date,
        end_date=end_date,
        period_type=period_type,
        limit=limit,
    )
    return TimeseriesResponse(
        instrument_id=instrument_id,
        metric=metric,
        data=[
            MetricDataPointResponse(
                as_of_date=dp.as_of_date,
                value_numeric=float(dp.value_numeric) if dp.value_numeric is not None else None,
                value_text=dp.value_text,
                period_type=dp.period_type,
            )
            for dp in data_points
        ],
    )


@router.post("/fundamentals/screen", response_model=ScreenResponse)
async def screen_instruments(
    body: ScreenRequest,
    uc: ScreenInstrumentsUseCase = Depends(get_screen_instruments_uc),  # type: ignore[assignment]
) -> ScreenResponse:
    """Screen instruments by metric thresholds.

    Uses the latest available value per instrument for each metric.
    All filters are combined with AND logic.
    """
    screen_filters = [
        ScreenFilter(
            metric=f.metric,
            min_value=f.min_value,
            max_value=f.max_value,
            period_type=f.period_type,
            sector=f.sector,
        )
        for f in body.filters
    ]
    results = await uc.execute(screen_filters, limit=body.limit, offset=body.offset)
    return ScreenResponse(
        results=[
            ScreenInstrumentResponse(
                instrument_id=r.instrument_id,
                metrics={k: float(v) if v is not None else None for k, v in r.metrics.items()},
            )
            for r in results
        ],
        count=len(results),
    )


@router.get("/fundamentals/metrics/{instrument_id}", response_model=AvailableMetricsResponse)
async def get_available_metrics(
    instrument_id: str,
    uc: GetAvailableFundamentalMetricsUseCase = Depends(get_available_metrics_uc),  # type: ignore[assignment]
) -> AvailableMetricsResponse:
    """Return all metric names available for an instrument in the read-optimised table."""
    metrics = await uc.execute(instrument_id)
    return AvailableMetricsResponse(
        instrument_id=instrument_id,
        metrics=metrics,
    )
