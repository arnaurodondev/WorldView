"""Prediction markets API router (PRD-0019 §6.2, Wave B-2).

Endpoints:
    GET /prediction-markets                     — list with filters
    GET /prediction-markets/{market_id}/history — time-series snapshots
    GET /prediction-markets/{market_id}         — detail (404 if not found)

R25: no infrastructure imports — all reads go through use cases.
R16: API layer uses only use cases.
Note: volume_24h is stored on snapshots, not on the market record. The list
endpoint pulls the latest snapshot volume via ``LEFT JOIN LATERAL`` in the
repo (PLAN-0048 D-1) and forwards it through the use case. The detail
endpoint still returns ``None`` (single-market view; can be wired similarly
later when needed).  The history endpoint exposes per-snapshot volume_24h
correctly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import (
    get_list_prediction_markets_uc,
    get_prediction_market_history_uc,
    get_prediction_market_uc,
)
from market_data.api.schemas.prediction_markets import (
    OutcomePriceResponse,
    PredictionMarketDetailResponse,
    PredictionMarketHistoryResponse,
    PredictionMarketsListResponse,
    PredictionMarketSummaryResponse,
    SnapshotPointResponse,
)
from market_data.application.use_cases.query_prediction_markets import (
    GetPredictionMarketHistoryUseCase,
    GetPredictionMarketUseCase,
    ListPredictionMarketsUseCase,
)

router = APIRouter(tags=["prediction-markets"])

_VALID_STATUS_VALUES = frozenset({"open", "resolved", "cancelled", "all"})


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


# ── List (literal path — registered before path-param routes) ────────────────


@router.get("/prediction-markets", response_model=PredictionMarketsListResponse)
async def list_prediction_markets(
    status: Annotated[str, Query(description="Filter by resolution status")] = "open",
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    uc: Annotated[ListPredictionMarketsUseCase, Depends(get_list_prediction_markets_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketsListResponse:
    """List prediction markets with optional status/text filters and pagination."""
    if status not in _VALID_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(_VALID_STATUS_VALUES))}",
        )
    pairs, total = await uc.execute(status=status, query=query, limit=limit, offset=offset)
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
            updated_at=market.updated_at,
        )
        for market, prices, volume in pairs
    ]
    return PredictionMarketsListResponse(items=items, total=total, limit=limit, offset=offset)


# ── History (/{market_id}/history — registered before /{market_id}) ──────────


@router.get(
    "/prediction-markets/{market_id}/history",
    response_model=PredictionMarketHistoryResponse,
)
async def get_prediction_market_history(
    market_id: str,
    from_dt: Annotated[datetime | None, Query(alias="from")] = None,
    to_dt: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    uc: Annotated[GetPredictionMarketHistoryUseCase, Depends(get_prediction_market_history_uc)] = ...,  # type: ignore[assignment]
) -> PredictionMarketHistoryResponse:
    """Return time-series probability snapshots for a prediction market."""
    try:
        snapshots = await uc.execute(market_id, from_dt=from_dt, to_dt=to_dt, limit=limit)
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
            )
            for snap in snapshots
        ],
    )


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
        updated_at=market.updated_at,
        created_at=market.created_at,
    )
