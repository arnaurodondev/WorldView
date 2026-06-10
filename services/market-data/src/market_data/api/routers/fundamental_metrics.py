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
    try:
        results, total = await uc.execute(
            [],
            limit=limit,
            offset=offset,
            sort_by=None,
            sort_order="asc",
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name == "QueryCanceledError" or "QueryCanceled" in exc_name:
            raise HTTPException(
                status_code=504, detail="Screener query timed out — try narrowing your filters."
            ) from None
        raise
    return ScreenResponse(
        results=[
            ScreenInstrumentResponse(
                instrument_id=r.instrument_id,
                ticker=r.ticker,
                name=r.name,
                exchange=r.exchange,
                sector=r.sector,
                metrics={
                    # Wave L-5c: date values serialize to ISO-8601 strings
                    # (``"2026-02-12"``) so they fit the response shape; the
                    # frontend renders dates the same way it would render any
                    # other string column. (Order matters: ``date`` must come
                    # before ``str`` because ``date.__str__`` is *not* str.)
                    k: (
                        v.isoformat()
                        if isinstance(v, date)
                        else (v if isinstance(v, str) else (float(v) if v is not None else None))
                    )
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
        # ── Wave L-4a snapshot fields (PLAN-0089) ────────────────────────────
        "analyst_target_price",
        "analyst_consensus_rating",
        "institutional_ownership_pct",
        "short_percent",
        # Wave L-5c: calendar (date) snapshot fields — sortable too (ASC =
        # soonest first, the natural reading for "next earnings" / "next div").
        "next_earnings_date",
        "next_dividend_date",
        # Wave L-4b: insider 90d sortable column.
        "insider_net_buy_90d",
        # ── Wave L-5b: intelligence rollup sortable columns (PLAN-0089) ──────
        "news_count_7d",
        "llm_relevance_7d_max",
        "display_relevance_7d_weighted",
        "recent_contradiction_count",
        "has_active_alert",
        "has_ai_brief",
    }
    # Wave L-3: computed OHLCV-derived metrics are addressable as sort targets too.
    # They are stored as fundamental_metrics rows (period_type=SNAPSHOT,
    # section=computed_returns), so the existing per-metric LATERAL JOIN handles
    # ORDER BY when the same name appears in ``filters[].metric``. To allow
    # ``sort_by`` to be set even when no explicit filter is present, we extend
    # the whitelist and the router will inject a no-bound ScreenFilter so the
    # query layer projects the column.
    computed_sort_fields = {
        "dist_from_52w_high_pct",
        "dist_from_52w_low_pct",
        "return_1m",
        "return_3m",
        "return_6m",
        "return_ytd",
        "return_1y",
        "return_3y",
    }
    # SQL injection guard: sort_by must be a filter metric name, "ticker", or "name"
    if body.sort_by is not None:
        valid_sort_fields = (
            {"ticker", "name"} | {f.metric for f in body.filters} | snap_sort_fields | computed_sort_fields
        )
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
            # ── Wave L-4a snapshot column predicates (PLAN-0089) ─────────────
            analyst_target_price_min=f.analyst_target_price_min,
            analyst_target_price_max=f.analyst_target_price_max,
            analyst_consensus_rating_min=f.analyst_consensus_rating_min,
            analyst_consensus_rating_max=f.analyst_consensus_rating_max,
            institutional_ownership_pct_min=f.institutional_ownership_pct_min,
            institutional_ownership_pct_max=f.institutional_ownership_pct_max,
            short_percent_min=f.short_percent_min,
            short_percent_max=f.short_percent_max,
            # Wave L-5c: calendar (date) filters — schema validates 0..365.
            next_earnings_within_days=f.next_earnings_within_days,
            next_dividend_within_days=f.next_dividend_within_days,
            # Wave L-4b: insider 90d range.
            insider_net_buy_90d_min=f.insider_net_buy_90d_min,
            insider_net_buy_90d_max=f.insider_net_buy_90d_max,
            # ── Wave L-5b: intelligence rollup filters (PLAN-0089) ────────────
            news_count_7d_min=f.news_count_7d_min,
            news_count_7d_max=f.news_count_7d_max,
            llm_relevance_7d_max_min=f.llm_relevance_7d_max_min,
            llm_relevance_7d_max_max=f.llm_relevance_7d_max_max,
            display_relevance_7d_weighted_min=f.display_relevance_7d_weighted_min,
            display_relevance_7d_weighted_max=f.display_relevance_7d_weighted_max,
            recent_contradiction_count_min=f.recent_contradiction_count_min,
            recent_contradiction_count_max=f.recent_contradiction_count_max,
            has_active_alert=f.has_active_alert,
            has_ai_brief=f.has_ai_brief,
        )
        for f in body.filters
    ]

    # Wave L-3 (T-WL3-04): expand any populated computed-metric *_min/*_max
    # shorthand fields into ScreenFilter(metric=<name>, min/max=...) entries.
    # Collapse across all filter entries with first non-None — same pattern as
    # the L-2 snap field handling in query_screen. This keeps the schema
    # ergonomic ("give me return_1y >= 0.20") while reusing the existing
    # latest-value-per-metric JOIN machinery.
    computed_fields = (
        "dist_from_52w_high_pct",
        "dist_from_52w_low_pct",
        "return_1m",
        "return_3m",
        "return_6m",
        "return_ytd",
        "return_1y",
        "return_3y",
    )
    existing_filter_metrics = {f.metric for f in screen_filters}
    for _field in computed_fields:
        min_attr = f"{_field}_min"
        max_attr = f"{_field}_max"
        _min = next(
            (getattr(f, min_attr) for f in body.filters if getattr(f, min_attr) is not None),
            None,
        )
        _max = next(
            (getattr(f, max_attr) for f in body.filters if getattr(f, max_attr) is not None),
            None,
        )
        # Also inject a no-bound filter if sort_by references the metric so the
        # column is projected for ORDER BY.
        _needs_for_sort = body.sort_by == _field and _field not in existing_filter_metrics
        if _min is None and _max is None and not _needs_for_sort:
            continue
        if _field in existing_filter_metrics:
            # Caller already passed an explicit filter on this metric; skip the
            # shorthand to avoid double-AND noise.
            continue
        screen_filters.append(
            ScreenFilter(
                metric=_field,
                min_value=_min,
                max_value=_max,
                period_type="SNAPSHOT",
            )
        )

    # asyncpg.QueryCanceledError fires when the 8s SET LOCAL statement_timeout
    # in query_screen is hit. Without this handler it surfaces as a 500 and
    # corrupts the connection pool (MissingGreenlet during cleanup). Map it to
    # 504 so callers can distinguish a timeout from a server error.
    try:
        results, total = await uc.execute(
            screen_filters,
            limit=body.limit,
            offset=body.offset,
            sort_by=body.sort_by,
            sort_order=body.sort_order,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name == "QueryCanceledError" or "QueryCanceled" in exc_name:
            raise HTTPException(
                status_code=504, detail="Screener query timed out — try narrowing your filters."
            ) from None
        raise
    return ScreenResponse(
        results=[
            ScreenInstrumentResponse(
                instrument_id=r.instrument_id,
                ticker=r.ticker,
                name=r.name,
                exchange=r.exchange,
                sector=r.sector,
                metrics={
                    # Wave L-5c: date values serialize to ISO-8601 strings
                    # (``"2026-02-12"``) so they fit the response shape; the
                    # frontend renders dates the same way it would render any
                    # other string column. (Order matters: ``date`` must come
                    # before ``str`` because ``date.__str__`` is *not* str.)
                    k: (
                        v.isoformat()
                        if isinstance(v, date)
                        else (v if isinstance(v, str) else (float(v) if v is not None else None))
                    )
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
