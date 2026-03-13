"""Pydantic schemas for instruments API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class InstrumentFlagsResponse(BaseModel):
    """Dataset capability flags for an instrument."""

    has_ohlcv: bool
    has_quotes: bool
    has_fundamentals: bool


class InstrumentResponse(BaseModel):
    """Single instrument response."""

    id: str
    security_id: str
    symbol: str
    exchange: str
    is_active: bool
    flags: InstrumentFlagsResponse
    created_at: datetime


class InstrumentListResponse(BaseModel):
    """Paginated list of instruments."""

    items: list[InstrumentResponse]
    total: int
    limit: int
    offset: int
