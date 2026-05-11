"""Pydantic schemas for OHLCV API responses."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class OHLCVBarResponse(BaseModel):
    """Single OHLCV bar response."""

    instrument_id: str
    timeframe: str
    bar_date: datetime
    open: str  # Decimal serialized as string to avoid float precision loss
    high: str
    low: str
    close: str
    volume: int | None
    adjusted_close: str | None = None
    source: str


class OHLCVListResponse(BaseModel):
    """Paginated list of OHLCV bars."""

    items: list[OHLCVBarResponse]
    total: int
    timeframe: str


class OHLCVRangeResponse(BaseModel):
    """Available date range for OHLCV data."""

    instrument_id: str
    timeframe: str
    min_date: date | None
    max_date: date | None
    count: int


# ── PLAN-0066 Wave G: temporal RAG endpoint schemas ────────────────────────────


class OHLCVFlexibleBar(BaseModel):
    """Single OHLCV bar in plain float representation (no Decimal string encoding).

    WHY float: The /ohlcv/bars endpoint is consumed by the rag-chat temporal RAG
    pipeline which needs arithmetic-ready numbers, not string-serialised Decimals.
    """

    date: str  # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCVBarsResponse(BaseModel):
    """Response for GET /api/v1/ohlcv/bars (temporal RAG PLAN-0066 Wave G)."""

    instrument_id: str
    ticker: str
    interval: str  # "day" | "week" | "month"
    bars: list[OHLCVFlexibleBar]
    bar_count: int
