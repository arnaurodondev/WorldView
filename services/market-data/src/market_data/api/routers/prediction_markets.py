"""Prediction markets API router (PRD-0019 §6.2, Wave B-2).

Endpoints:
    GET /prediction-markets                          — list with filters
    GET /prediction-markets/categories               — per-category open counts
    GET /prediction-markets/events                   — list event groups (PLAN-0056 A4)
    GET /prediction-markets/events/{event_id}        — single event (404) (PLAN-0056 A4)
    GET /prediction-markets/{market_id}/history      — snapshots, or interval price bars
                                                       when ?interval=1h|1d|1w (PLAN-0056 A4)
    GET /prediction-markets/{market_id}/trades       — recent fills (PLAN-0056 A4)
    GET /prediction-markets/{market_id}              — detail (404 if not found)

R25: no infrastructure imports — all reads go through use cases.
R16: API layer uses only use cases.
Note: volume_24h is authored on snapshots (per-poll), but the list endpoint
reads it from ``prediction_markets.latest_volume_24h`` — a column
denormalized at snapshot-write time (migration 048) — and forwards it
through the use case. This replaced an earlier ``LEFT JOIN LATERAL``
(PLAN-0048 D-1) that re-derived the latest volume per row on every request;
under load that per-row join occasionally tipped over the DB
``statement_timeout`` and 500'd the endpoint. The detail endpoint still
returns ``None`` (single-market view; can be wired similarly later when
needed). The history endpoint exposes per-snapshot volume_24h correctly.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import (
    get_count_prediction_market_categories_uc,
    get_list_prediction_events_uc,
    get_list_prediction_markets_uc,
    get_prediction_event_uc,
    get_prediction_market_history_uc,
    get_prediction_market_price_history_uc,
    get_prediction_market_trades_uc,
    get_prediction_market_uc,
)
from market_data.api.schemas.prediction_markets import (
    CategoryCountResponse,
    OutcomePriceResponse,
    PredictionEventResponse,
    PredictionEventsListResponse,
    PredictionMarketCategoriesResponse,
    PredictionMarketDetailResponse,
    PredictionMarketHistoryResponse,
    PredictionMarketPriceHistoryResponse,
    PredictionMarketsListResponse,
    PredictionMarketSummaryResponse,
    PredictionMarketTradeResponse,
    PredictionMarketTradesResponse,
    PriceHistoryPointResponse,
    SnapshotPointResponse,
)
from market_data.application.use_cases.query_prediction_markets import (
    CountPredictionMarketCategoriesUseCase,
    GetPredictionEventUseCase,
    GetPredictionMarketHistoryUseCase,
    GetPredictionMarketPriceHistoryUseCase,
    GetPredictionMarketTradesUseCase,
    GetPredictionMarketUseCase,
    ListPredictionEventsUseCase,
    ListPredictionMarketsUseCase,
)

if TYPE_CHECKING:
    from market_data.domain.entities import PredictionEvent

router = APIRouter(tags=["prediction-markets"])

_VALID_STATUS_VALUES = frozenset({"open", "resolved", "cancelled", "all"})
# PLAN-0056 A4: the interval price-history endpoint accepts only these bucket
# labels on the wire.  The underlying hypertable stores free-form intervals
# (BP-007 — never a PG enum), but the API surface is intentionally narrow so
# the frontend chart can offer a fixed set of resolutions.
_VALID_INTERVAL_VALUES = frozenset({"1h", "1d", "1w"})


def _build_outcomes(
    market_outcomes: list[dict],
    prices: dict[str, float],
) -> list[OutcomePriceResponse]:
    """Assemble OutcomePriceResponse list from market outcomes + latest prices.

    Falls back to 0.0 for any outcome whose name is not in ``prices``.
    """
    return [
        OutcomePriceResponse(
            name=o.get("name", ""),
            token_id=o.get("token_id", ""),
            price=prices.get(o.get("name", ""), 0.0),
        )
        for o in market_outcomes
    ]


def _build_event_response(event: PredictionEvent) -> PredictionEventResponse:
    """Map a ``PredictionEvent`` domain entity to its wire schema (PLAN-0056 A4)."""
    return PredictionEventResponse(
        event_id=event.event_id,
        name=event.name,
        category=event.category,
        start_date=event.start_date,
        end_date=event.end_date,
        market_count=event.market_count,
    )


# ── List (literal path — registered before path-param routes) ────────────────


@router.get("/prediction-markets", response_model=PredictionMarketsListResponse)
async def list_prediction_markets(
    status: Annotated[str, Query(description="Filter by resolution status")] = "open",
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    # PLAN-0049 T-C-3-03 — high-level category tag.  Documented values:
    # ``macro`` | ``politics`` | ``sports`` | ``crypto`` | ``general``.
    # The backend does NOT validate the enum: future Polymarket tags can
    # be passed through without a code change here.  ``max_length=50``
    # mirrors the column width.
    category: Annotated[
        str | None,
        Query(
            max_length=50,
            description=(
                "Optional category filter. Suggested values: macro, "
                "politics, sports, crypto, general (non-binding — backend "
                "does case-insensitive equality only)."
            ),
        ),
    ] = None,
    uc: Annotated[ListPredictionMarketsUseCase, Depends(get_list_prediction_markets_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketsListResponse:
    """List prediction markets with optional status/text/category filters and pagination."""
    if status not in _VALID_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(_VALID_STATUS_VALUES))}",
        )
    pairs, total = await uc.execute(
        status=status,
        query=query,
        limit=limit,
        offset=offset,
        category=category,
    )
    # WHY float() with None-guard: ``volume_24h`` is a ``Decimal`` from the DB
    # (precision-preserving on the wire side).  PLAN-0048 D-1: previously this
    # was hardcoded to ``None`` because it required a separate query; the
    # repo now JOINs the latest snapshot inline so we can forward the value.
    # Pydantic ``float | None`` accepts None — so markets without snapshots
    # still serialise cleanly.
    items = [
        PredictionMarketSummaryResponse(
            market_id=market.market_id,
            question=market.question,
            outcomes=_build_outcomes(market.outcomes, prices),
            volume_24h=float(volume) if volume is not None else None,
            close_time=market.close_time,
            resolution_status=market.resolution_status,
            resolved_answer=market.resolved_answer,
            market_slug=market.market_slug,
            category=market.category,
            updated_at=market.updated_at,
        )
        for market, prices, volume in pairs
    ]
    return PredictionMarketsListResponse(items=items, total=total, limit=limit, offset=offset)


# ── Categories (literal path — registered before any /{market_id} routes) ────


@router.get(
    "/prediction-markets/categories",
    response_model=PredictionMarketCategoriesResponse,
)
async def get_prediction_market_categories(
    uc: Annotated[
        CountPredictionMarketCategoriesUseCase,
        Depends(get_count_prediction_market_categories_uc),
    ] = ...,  # type: ignore[assignment]
) -> PredictionMarketCategoriesResponse:
    """Return per-category counts of currently-open prediction markets.

    PLAN-0053 T-C-3-05.

    WHY a dedicated endpoint (rather than aggregating in the list endpoint):
    the dashboard needs the counts even when the user has applied a category
    filter — at which point the list endpoint only returns rows for that
    category. A separate endpoint stays cheap (single GROUP BY query) and
    keeps the list endpoint shape stable.

    Response shape mirrors the rest of the API:
        ``{"items": [{"category": "macro", "count": 12}, ...], "total": 87}``

    ``category`` may be ``null`` for legacy rows. Frontend typically treats
    NULL as "uncategorized" or hides it.
    """
    pairs = await uc.execute()
    items = [CategoryCountResponse(category=cat, count=count) for cat, count in pairs]
    # WHY total = sum: the GROUP BY already gives us the per-category counts;
    # summing locally avoids a second SQL round-trip and stays consistent
    # with the per-category numbers above.
    total = sum(count for _cat, count in pairs)
    return PredictionMarketCategoriesResponse(items=items, total=total)


# ── History (/{market_id}/history — registered before /{market_id}) ──────────


@router.get(
    "/prediction-markets/{market_id}/history",
    response_model=PredictionMarketHistoryResponse | PredictionMarketPriceHistoryResponse,
)
async def get_prediction_market_history(
    market_id: str,
    from_dt: Annotated[datetime | None, Query(alias="from")] = None,
    to_dt: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    # PLAN-0056 A4: when ``interval`` is supplied we serve real per-token
    # interval bars from the ``prediction_market_prices`` hypertable instead of
    # raw snapshots.  Omitting ``interval`` keeps the original snapshot
    # behaviour — backward-compatible for every existing caller.
    interval: Annotated[
        str | None,
        Query(description="Optional price-bar interval: 1h, 1d, or 1w. Omit for raw snapshots."),
    ] = None,
    # Optional narrowing to a single outcome token when reading interval bars.
    token_id: Annotated[str | None, Query(description="Optional token filter for interval history.")] = None,
    snapshot_uc: Annotated[GetPredictionMarketHistoryUseCase, Depends(get_prediction_market_history_uc)] = ...,  # type: ignore[assignment]
    price_uc: Annotated[GetPredictionMarketPriceHistoryUseCase, Depends(get_prediction_market_price_history_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketHistoryResponse | PredictionMarketPriceHistoryResponse:
    """Return history for a prediction market.

    Without ``interval``: raw probability snapshots (unchanged legacy shape).
    With ``interval`` (1h|1d|1w): per-token interval price bars from the prices
    hypertable (PLAN-0056 A4).
    """
    # ── interval branch: read the prices hypertable ─────────────────────────
    if interval is not None:
        if interval not in _VALID_INTERVAL_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"interval must be one of: {', '.join(sorted(_VALID_INTERVAL_VALUES))}",
            )
        try:
            prices = await price_uc.execute(
                market_id,
                interval=interval,
                token_id=token_id,
                from_dt=from_dt,
                to_dt=to_dt,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if prices is None:
            raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found")

        return PredictionMarketPriceHistoryResponse(
            market_id=market_id,
            interval=interval,
            points=[
                PriceHistoryPointResponse(
                    window_start_ts=p.window_start_ts,
                    price=float(p.price),
                    interval=p.interval,
                    token_id=p.token_id,
                    outcome_name=p.outcome_name,
                )
                for p in prices
            ],
        )

    # ── default branch: raw snapshots (legacy behaviour) ────────────────────
    try:
        snapshots = await snapshot_uc.execute(market_id, from_dt=from_dt, to_dt=to_dt, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshots is None:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found")

    return PredictionMarketHistoryResponse(
        market_id=market_id,
        snapshots=[
            SnapshotPointResponse(
                snapshot_at=snap.snapshot_at,
                outcomes_prices=snap.outcomes_prices,
                volume_24h=float(snap.volume_24h) if snap.volume_24h is not None else None,
                # PLAN-0056 A1: expose per-snapshot liquidity. The domain entity
                # already carries it as Decimal|None; None survives unchanged.
                liquidity=float(snap.liquidity) if snap.liquidity is not None else None,
            )
            for snap in snapshots
        ],
    )


# ── Trades (/{market_id}/trades — registered before /{market_id}) ────────────


@router.get(
    "/prediction-markets/{market_id}/trades",
    response_model=PredictionMarketTradesResponse,
)
async def get_prediction_market_trades(
    market_id: str,
    since: Annotated[datetime | None, Query(description="Only trades at/after this UTC time.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    uc: Annotated[GetPredictionMarketTradesUseCase, Depends(get_prediction_market_trades_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketTradesResponse:
    """Return recent executed fills for a prediction market, newest first."""
    trades = await uc.execute(market_id, since=since, limit=limit)
    if trades is None:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found")

    return PredictionMarketTradesResponse(
        market_id=market_id,
        limit=limit,
        items=[
            PredictionMarketTradeResponse(
                ts=t.ts,
                price=float(t.price),
                # ``size_usd`` is Decimal|None — None survives unchanged.
                size_usd=float(t.size_usd) if t.size_usd is not None else None,
                side=t.side,
                token_id=t.token_id,
            )
            for t in trades
        ],
    )


# ── Events (literal /events — registered before any /{market_id} routes) ─────


@router.get(
    "/prediction-markets/events",
    response_model=PredictionEventsListResponse,
)
async def list_prediction_events(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    uc: Annotated[ListPredictionEventsUseCase, Depends(get_list_prediction_events_uc)] = ...,  # type: ignore[assignment]
) -> PredictionEventsListResponse:
    """List Polymarket event groups (newest first) with pagination."""
    events, total = await uc.execute(limit=limit, offset=offset)
    return PredictionEventsListResponse(
        items=[_build_event_response(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/prediction-markets/events/{event_id}",
    response_model=PredictionEventResponse,
)
async def get_prediction_event(
    event_id: str,
    uc: Annotated[GetPredictionEventUseCase, Depends(get_prediction_event_uc)] = ...,  # type: ignore[assignment]
) -> PredictionEventResponse:
    """Return a single prediction event by ``event_id`` (404 if not found)."""
    event = await uc.execute(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
    return _build_event_response(event)


# ── Detail (/{market_id} — registered after /{market_id}/history) ────────────


@router.get(
    "/prediction-markets/{market_id}",
    response_model=PredictionMarketDetailResponse,
)
async def get_prediction_market(
    market_id: str,
    uc: Annotated[GetPredictionMarketUseCase, Depends(get_prediction_market_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketDetailResponse:
    """Return full detail for a single prediction market."""
    result = await uc.execute(market_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found")

    market, prices, volume = result
    # WHY float() with None-guard: ``volume_24h`` is ``Decimal`` from the
    # snapshot row.  ``None`` survives unchanged for markets without a
    # snapshot.  PLAN-0048 D-1.
    return PredictionMarketDetailResponse(
        market_id=market.market_id,
        question=market.question,
        description=market.description,
        outcomes=_build_outcomes(market.outcomes, prices),
        volume_24h=float(volume) if volume is not None else None,
        close_time=market.close_time,
        resolution_status=market.resolution_status,
        resolved_answer=market.resolved_answer,
        market_slug=market.market_slug,
        category=market.category,
        updated_at=market.updated_at,
        created_at=market.created_at,
    )
