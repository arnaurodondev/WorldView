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


class TopByMarketCapItem(BaseModel):
    """One row in the top-N-by-market-cap response.

    ``market_cap_usd`` is the latest known capitalisation from
    ``fundamental_metrics`` (metric=``market_capitalization``); may be
    ``None`` for newly-listed instruments that have not yet been ingested.
    """

    id: str
    symbol: str
    exchange: str
    market_cap_usd: float | None = None
    currency_code: str | None = None


class TopByMarketCapResponse(BaseModel):
    """Paginated list of instruments sorted by latest market cap (desc)."""

    total: int
    offset: int
    limit: int
    results: list[TopByMarketCapItem]


class OhlcvCoveredItem(BaseModel):
    """One row in the ohlcv-covered response (PLAN-0089 Wave L-4b).

    Lightweight subset of InstrumentResponse — used by market-ingestion's
    universe-expansion call so the worker can build new policy rows.
    """

    id: str
    symbol: str
    exchange: str
    country: str | None = None
    currency_code: str | None = None


class OhlcvCoveredResponse(BaseModel):
    """Paginated list of instruments with ``has_ohlcv = TRUE``."""

    total: int
    offset: int
    limit: int
    results: list[OhlcvCoveredItem]


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
