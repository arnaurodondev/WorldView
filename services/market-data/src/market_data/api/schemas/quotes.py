"""Pydantic schemas for quotes API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class QuoteResponse(BaseModel):
    """Single quote snapshot response."""

    instrument_id: str
    bid: str | None  # Decimal as string; None when not available
    ask: str | None
    last: str | None
    volume: int | None
    timestamp: datetime
    updated_at: datetime


class BatchQuoteRequest(BaseModel):
    """Request body for batch quote lookup."""

    instrument_ids: list[str]


class BatchQuoteResponse(BaseModel):
    """Response for a batch of quote lookups."""

    quotes: dict[str, QuoteResponse | None]
