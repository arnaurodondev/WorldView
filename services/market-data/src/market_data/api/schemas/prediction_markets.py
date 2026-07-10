"""Pydantic response schemas for the prediction markets API (PRD-0019 §6.2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OutcomePriceResponse(BaseModel):
    """Current price (implied probability) for a single market outcome."""

    name: str
    token_id: str
    price: float


class PredictionMarketSummaryResponse(BaseModel):
    """Summary view of a prediction market — used in list responses."""

    market_id: str
    question: str
    outcomes: list[OutcomePriceResponse]
    volume_24h: float | None
    close_time: datetime | None
    resolution_status: str
    resolved_answer: str | None
    updated_at: datetime
    # WHY default None: added in migration 009; existing rows return null until
    # the consumer repopulates them on the next poll cycle.
    market_slug: str | None = None
    # F-QAC-07 fix (PLAN-0049 T-C-3-03): expose `category` on the wire so
    # frontends can render category badges per row, not just filter on it.
    # Default None matches migration 010 (nullable column, no server_default)
    # — existing rows surface as `category: null` until adapter backfills.
    category: str | None = None


class PredictionMarketDetailResponse(PredictionMarketSummaryResponse):
    """Full detail view of a prediction market — includes description + created_at."""

    description: str | None
    created_at: datetime


class PredictionMarketsListResponse(BaseModel):
    """Paginated list of prediction market summaries."""

    items: list[PredictionMarketSummaryResponse]
    total: int
    limit: int
    offset: int


class SnapshotPointResponse(BaseModel):
    """One time-series data point from the prediction market snapshot hypertable."""

    snapshot_at: datetime
    outcomes_prices: dict[str, float]
    volume_24h: float | None
    # PLAN-0056 A1: the domain snapshot already carries ``liquidity`` (Decimal)
    # and the repo already maps + selects it — it was simply not surfaced on the
    # wire. Default None so historical rows / markets without a liquidity value
    # serialise cleanly as ``liquidity: null``.
    liquidity: float | None = None


class PredictionMarketHistoryResponse(BaseModel):
    """Time-series of probability snapshots for a single market."""

    market_id: str
    snapshots: list[SnapshotPointResponse]


class CategoryCountResponse(BaseModel):
    """One row of the per-category counts response (PLAN-0053 T-C-3-05).

    ``category`` may be ``None`` for rows that have no category in the DB
    (legacy ingestions, providers other than Polymarket). Frontends typically
    bucket NULL into "uncategorized" or hide it.
    """

    category: str | None
    count: int


class PredictionMarketCategoriesResponse(BaseModel):
    """Top-level response for ``GET /v1/prediction-markets/categories``.

    Returns ``items`` (per-category counts, sorted desc by count) plus a
    convenience ``total`` over all open markets so the frontend can render
    "All N" without summing the per-category counts client-side.
    """

    items: list[CategoryCountResponse]
    total: int
