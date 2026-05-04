"""Instrument and market-data response schemas.

WHY: These Pydantic models mirror the TypeScript interfaces in
apps/worldview-web/types/api.ts (OHLCVBar, OHLCVResponse, Quote, SearchResult).
Adding them as response_model= on S9 proxy routes generates named OpenAPI
component schemas so pnpm generate-types produces correct TypeScript aliases.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class InstrumentSearchResult(BaseModel):
    """Single search result from GET /v1/search/instruments.

    Mirrors the SearchResult TypeScript interface in types/api.ts.
    WHY extra=allow: S3 may add fields (e.g. asset_class, gics_sector)
    without requiring a gateway schema change.
    """

    model_config = ConfigDict(extra="allow")

    instrument_id: str
    ticker: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    asset_class: str | None = None


class OHLCVBar(BaseModel):
    """One OHLCV bar.

    Mirrors the OHLCVBar TypeScript interface in types/api.ts.
    WHY volume is optional: S3 returns null volume for some synthetic
    instruments (e.g. indices) where volume data is unavailable.
    """

    model_config = ConfigDict(extra="allow")

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class OHLCVResponse(BaseModel):
    """Response from GET /v1/ohlcv/{instrument_id}.

    Mirrors the OHLCVResponse TypeScript interface in types/api.ts.
    """

    model_config = ConfigDict(extra="allow")

    instrument_id: str
    ticker: str | None = None
    timeframe: str
    bars: list[OHLCVBar] = []


class QuoteResponse(BaseModel):
    """Response from GET /v1/quotes/{instrument_id}.

    Mirrors the Quote TypeScript interface in types/api.ts.
    WHY many optional fields: freshness fields were added in PLAN-0036 Wave 1;
    older quote responses from the legacy S3 endpoint may not include them.
    """

    model_config = ConfigDict(extra="allow")

    instrument_id: str
    ticker: str | None = None
    price: float
    change: float | None = None
    change_pct: float | None = None
    timestamp: str | None = None
    volume: int | None = None
