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


class PredictionMarketHistoryResponse(BaseModel):
    """Time-series of probability snapshots for a single market."""

    market_id: str
    snapshots: list[SnapshotPointResponse]
