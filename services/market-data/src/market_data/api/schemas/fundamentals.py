"""Pydantic schemas for fundamentals API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class FundamentalsRecordResponse(BaseModel):
    """Single fundamentals record for a given section and period."""

    id: str
    security_id: str
    section: str
    period_end: datetime
    period_type: str
    data: dict[str, Any]
    source: str
    ingested_at: datetime


class FundamentalsResponse(BaseModel):
    """All fundamentals records for a security (all sections)."""

    security_id: str
    records: list[FundamentalsRecordResponse]
