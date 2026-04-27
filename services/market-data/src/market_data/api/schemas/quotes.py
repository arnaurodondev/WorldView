"""Pydantic schemas for quotes API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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

    instrument_ids: list[str] = Field(min_length=1, max_length=200)  # F-SEC-006: prevent DoS amplification

    @field_validator("instrument_ids", mode="before")
    @classmethod
    def validate_uuids(cls, v: object) -> object:
        """Reject non-UUID instrument_ids early (422 not 500).

        The DB quotes table uses a UUID PK column — passing a ticker symbol like
        "SPY" causes an asyncpg DataError at the SQL layer. Returning 422 here
        gives a clear error instead of an opaque 500.
        """
        if not isinstance(v, list):
            return v
        for item in v:
            try:
                UUID(str(item))
            except ValueError as exc:
                raise ValueError(f"instrument_ids must be valid UUIDs; got {item!r}") from exc
        return v


class BatchQuoteResponse(BaseModel):
    """Response for a batch of quote lookups."""

    quotes: dict[str, QuoteResponse | None]
