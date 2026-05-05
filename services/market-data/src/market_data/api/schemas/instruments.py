"""Pydantic schemas for instruments API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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


class InstrumentLookupResponse(BaseModel):
    """Minimal instrument lookup result (no extra_info)."""

    id: str
    symbol: str
    exchange: str
    is_active: bool


class InstrumentLookupDetailResponse(InstrumentLookupResponse):
    """Full instrument lookup result (extra_info=true) — extends base with enrichment fields."""

    name: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency_code: str | None = None
    description: str | None = None


class OnDemandProfileResponse(BaseModel):
    """Structured enrichment profile fetched on-demand from EODHD and DB."""

    instrument_id: str
    security_id: str
    ticker: str
    exchange: str
    isin: str | None
    currency_code: str | None
    description: str | None
    sector: str | None
    industry: str | None
    country: str | None
    source: Literal["db", "eodhd_persisted"]
