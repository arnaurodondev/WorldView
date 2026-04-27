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
