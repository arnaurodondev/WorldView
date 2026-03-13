"""Pydantic request/response schemas for the market-ingestion API."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TriggerRequest(BaseModel):
    """Request body for POST /api/v1/ingest/trigger."""

    provider: str
    symbols: list[str]
    dataset_type: str
    timeframe: str = "1d"
    exchange: str | None = None

    @field_validator("symbols")
    @classmethod
    def symbols_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("symbols must not be empty")
        return v


class BackfillRequest(BaseModel):
    """Request body for POST /api/v1/ingest/backfill."""

    provider: str
    symbol: str
    start_date: date
    end_date: date
    timeframe: str = "1d"
    chunk_days: int = 30
    exchange: str | None = None

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TriggerResponse(BaseModel):
    """Response for POST /api/v1/ingest/trigger."""

    tasks_created: int
    tasks_skipped: int
    symbols: list[str]


class BackfillResponse(BaseModel):
    """Response for POST /api/v1/ingest/backfill."""

    tasks_created: int
    tasks_skipped: int
    chunks: int
    symbol: str


class TaskStatusResponse(BaseModel):
    """Response for GET /api/v1/ingest/status."""

    counts: dict[str, int]
    total: int


class PolicySummary(BaseModel):
    """Summary of a single polling policy."""

    id: str
    provider: str
    dataset_type: str
    symbol: str | None
    timeframe: str | None
    base_interval_seconds: float
    is_enabled: bool
    priority: int


class PolicyListResponse(BaseModel):
    """Response for GET /api/v1/policies."""

    policies: list[PolicySummary]
    total: int


class HealthResponse(BaseModel):
    """Response for /healthz."""

    status: str


class ReadyResponse(BaseModel):
    """Response for /readyz."""

    status: str
    checks: dict[str, str]
