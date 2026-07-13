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


class PriceHistoryPointResponse(BaseModel):
    """One interval price bar for a single token (PLAN-0056 A4).

    Sourced from the ``prediction_market_prices`` hypertable. ``price`` is a
    ``Decimal`` in the domain (NUMERIC(12,6)); it serialises to a float on the
    wire. ``interval`` is the free-form bucket label (``1h`` / ``1d`` / ``1w``);
    ``outcome_name`` may be ``null`` when the feed didn't label the token.
    """

    window_start_ts: datetime
    price: float
    interval: str
    token_id: str
    outcome_name: str | None = None


class PredictionMarketPriceHistoryResponse(BaseModel):
    """Interval price-history series for a single market (PLAN-0056 A4).

    Returned by ``GET /prediction-markets/{market_id}/history?interval=…``.
    Distinct shape from ``PredictionMarketHistoryResponse`` (snapshots): this
    is the per-token interval-bar view keyed by ``points``.
    """

    market_id: str
    interval: str
    points: list[PriceHistoryPointResponse]


class PredictionMarketTradeResponse(BaseModel):
    """One executed fill on a market's token (PLAN-0056 A4).

    ``size_usd`` may be ``null`` (some feeds omit notional). ``side`` is a
    free-form label (``buy`` / ``sell``).
    """

    ts: datetime
    price: float
    size_usd: float | None
    side: str
    token_id: str


class PredictionMarketTradesResponse(BaseModel):
    """Recent trades for a single market, newest first (PLAN-0056 A4)."""

    market_id: str
    items: list[PredictionMarketTradeResponse]
    limit: int


class PredictionEventResponse(BaseModel):
    """A Polymarket "event" group — a set of related markets (PLAN-0056 A4).

    ``market_count`` is denormalised on the event row (number of child markets).
    ``category`` / ``start_date`` / ``end_date`` may be ``null`` for events the
    feed didn't fully populate.
    """

    event_id: str
    name: str
    category: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    market_count: int = 0


class PredictionEventsListResponse(BaseModel):
    """Paginated list of prediction events (PLAN-0056 A4)."""

    items: list[PredictionEventResponse]
    total: int
    limit: int
    offset: int


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
