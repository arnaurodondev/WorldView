"""Pydantic schemas for securities API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SecurityResponse(BaseModel):
    """Single security response."""

    id: str
    figi: str | None
    isin: str | None
    name: str
    sector: str | None
    industry: str | None
    country: str | None
    currency: str | None
    created_at: datetime
    updated_at: datetime


class SecurityListResponse(BaseModel):
    """List of securities."""

    items: list[SecurityResponse]
    total: int
