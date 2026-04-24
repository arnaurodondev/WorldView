"""Pydantic schemas for the price-snapshot API endpoints.

These schemas define the wire format for GET /internal/v1/price/{instrument_id}
and POST /internal/v1/price/batch.  Decimal fields are serialised as strings to
preserve precision across JSON boundaries (avoids float rounding).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PriceSnapshotResponse(BaseModel):
    """Single resolved price snapshot — response schema for the price API."""

    # Instrument identification
    instrument_id: str
    symbol: str
    exchange: str

    # Price data — Decimal serialised as string to preserve precision
    price: str
    price_change: str | None  # absolute change vs previous close; None if unknown
    price_change_pct: str | None  # percentage change vs previous close; None if unknown

    # Timestamps (UTC-aware ISO-8601)
    timestamp: datetime  # when the underlying price was valid
    fetched_at: datetime  # when this snapshot was resolved

    # Provenance and staleness metadata
    source: str  # PriceSource string value (e.g. "fresh_quote", "daily_close")
    freshness_status: str  # FreshnessStatus string value (e.g. "live", "stale")
    stale_reason: str | None  # human-readable staleness explanation; None if fresh

    # Refresh eligibility (for rate-limited on-demand refresh UX)
    refresh_available: bool
    refresh_cooldown_remaining_sec: int


class BatchPriceSnapshotRequest(BaseModel):
    """Request body for the batch price-snapshot endpoint (POST)."""

    # Between 1 and 50 instrument UUIDs per request to prevent DoS amplification
    instrument_ids: list[str] = Field(min_length=1, max_length=50)
