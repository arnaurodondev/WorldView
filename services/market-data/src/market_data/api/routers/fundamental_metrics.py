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
    get_screen_fields_uc,
    get_screen_instruments_uc,
    get_timeseries_uc,
)
from market_data.api.schemas.fundamental_metrics import (
    AvailableMetricsResponse,
    MetricDataPointResponse,
    ScreenFieldResponse,
    ScreenFieldsResponse,
    ScreenInstrumentResponse,
    ScreenRequest,
    ScreenResponse,
    TimeseriesResponse,
)
from market_data.application.ports.repositories import ScreenFilter
from market_data.application.use_cases.query_fundamental_metrics import (
    GetAvailableFundamentalMetricsUseCase,
    GetFundamentalMetricsTimeseriesUseCase,
    ScreenFieldsMetadataUseCase,
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
    order: Annotated[
        str,
        Query(
            pattern="^(asc|desc)$",
            description=(
                "Fetch ordering. Use 'desc' with a small limit to get the most-recent N points "
                "(typical UI sparkline use case). Returned data is always sorted ASC by date for "
                "chronological rendering. Default 'asc' preserves prior behaviour."
            ),
        ),
    ] = "asc",
    uc: GetFundamentalMetricsTimeseriesUseCase = Depends(get_timeseries_uc),  # type: ignore[assignment]
) -> TimeseriesResponse:
    """Return timeseries data for a single instrument and metric.

    Query the read-optimised ``fundamental_metrics`` table.

    Audit 2026-05-09: ``order`` previously existed only on the frontend
    contract — it was sent over the wire but ignored by the router and the
    underlying query helper. Charts on the Fundamentals tab consequently
    rendered the OLDEST 12 quarters (1985-1988 for AAPL) instead of the
    most-recent. Now wired end-to-end.
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
        order=order,
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


# PLAN-0059 W0 fix F-010 (2026-04-30): GET /fundamentals/screen route added so
# the frontend convenience call (no body) works. Previously a GET hit the
# /fundamentals/{instrument_id} route, asyncpg rejected "screen" as a UUID,
# returned 500. Now GET delegates to the same use case with default filters.
@router.get("/fundamentals/screen", response_model=ScreenResponse)
async def screen_instruments_get(
    limit: int = 50,
    offset: int = 0,
    uc: ScreenInstrumentsUseCase = Depends(get_screen_instruments_uc),  # type: ignore[assignment]
) -> ScreenResponse:
    """Empty-filter screen — returns the first `limit` instruments by ticker.

    Convenience GET endpoint mirroring POST /fundamentals/screen with no
    filters. Useful for frontend sanity checks and the screener default state.
    """
    results, total = await uc.execute(
        [],
        limit=limit,
        offset=offset,
        sort_by=None,
        sort_order="asc",
    )
    return ScreenResponse(
        results=[
            ScreenInstrumentResponse(
                instrument_id=r.instrument_id,
                ticker=r.ticker,
                name=r.name,
                exchange=r.exchange,
                sector=r.sector,
                metrics={
                    k: (v if isinstance(v, str) else (float(v) if v is not None else None))
                    for k, v in r.metrics.items()
                },
            )
            for r in results
        ],
        count=len(results),
        total=total,
    )


@router.post("/fundamentals/screen", response_model=ScreenResponse)
async def screen_instruments(
    body: ScreenRequest,
    uc: ScreenInstrumentsUseCase = Depends(get_screen_instruments_uc),  # type: ignore[assignment]
) -> ScreenResponse:
    """Screen instruments by metric thresholds.

    Uses the latest available value per instrument for each metric.
    All filters are combined with AND logic.

    ``sort_by`` is validated against a whitelist (filter metric names + ``ticker``
    and ``name``) to prevent SQL injection (PRD-0017 §6.8, §8).
    """
    # Wave L-2 snapshot fields are also valid sort/sortable targets even
    # though they are not addressed via the ``filters[].metric`` channel —
    # they live on the LEFT-JOINed ``instrument_fundamentals_snapshot`` row
    # and are always projected into every result, so sorting by them is
    # always meaningful.
    snap_sort_fields = {
        "avg_volume_30d",
        "eps_ttm",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
    }
    # SQL injection guard: sort_by must be a filter metric name, "ticker", or "name"
    if body.sort_by is not None:
        valid_sort_fields = {"ticker", "name"} | {f.metric for f in body.filters} | snap_sort_fields
        if body.sort_by not in valid_sort_fields:
            raise HTTPException(
                status_code=422,
                detail=f"sort_by must be one of: {', '.join(sorted(valid_sort_fields))}",
            )

    screen_filters = [
        ScreenFilter(
            metric=f.metric,
            min_value=f.min_value,
            max_value=f.max_value,
            period_type=f.period_type,
            sector=f.sector,
            industry=f.industry,
            country=f.country,
            exchange=f.exchange,
            has_fundamentals=f.has_fundamentals,
            has_ohlcv=f.has_ohlcv,
            # Wave L-2: snapshot column predicates (numeric ranges + rating IN).
            avg_volume_30d_min=f.avg_volume_30d_min,
            avg_volume_30d_max=f.avg_volume_30d_max,
            eps_ttm_min=f.eps_ttm_min,
            eps_ttm_max=f.eps_ttm_max,
            free_cash_flow_min=f.free_cash_flow_min,
            free_cash_flow_max=f.free_cash_flow_max,
            fcf_margin_min=f.fcf_margin_min,
            fcf_margin_max=f.fcf_margin_max,
            interest_coverage_min=f.interest_coverage_min,
            interest_coverage_max=f.interest_coverage_max,
            net_debt_to_ebitda_min=f.net_debt_to_ebitda_min,
            net_debt_to_ebitda_max=f.net_debt_to_ebitda_max,
            credit_ratings=tuple(f.credit_ratings) if f.credit_ratings else None,
        )
        for f in body.filters
    ]
    results, total = await uc.execute(
        screen_filters,
        limit=body.limit,
        offset=body.offset,
        sort_by=body.sort_by,
        sort_order=body.sort_order,
    )
    return ScreenResponse(
        results=[
            ScreenInstrumentResponse(
                instrument_id=r.instrument_id,
                ticker=r.ticker,
                name=r.name,
                exchange=r.exchange,
                sector=r.sector,
                metrics={
                    k: (v if isinstance(v, str) else (float(v) if v is not None else None))
                    for k, v in r.metrics.items()
                },
            )
            for r in results
        ],
        count=len(results),
        total=total,
    )


@router.get("/fundamentals/screen/fields", response_model=ScreenFieldsResponse)
async def get_screen_fields(
    uc: ScreenFieldsMetadataUseCase = Depends(get_screen_fields_uc),  # type: ignore[assignment]
) -> ScreenFieldsResponse:
    """Return metadata for all screenable fields.

    The frontend uses this to build the filter form dynamically (PRD-0017 §6.2).
    Auth: none (public). Backed by Valkey cache; falls back to DB on miss.
    """
    fields = await uc.execute()
    return ScreenFieldsResponse(
        fields=[
            ScreenFieldResponse(
                name=f.name,
                label=f.label,
                type=f.field_type,
                unit=f.unit,
                description=f.description,
                observed_min=f.observed_min,
                observed_max=f.observed_max,
                null_fraction=f.null_fraction,
            )
            for f in fields
        ]
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
