"""Pydantic request/response schemas for the market-ingestion API."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TriggerRequest(BaseModel):
    """Request body for POST /api/v1/ingest/trigger."""

    provider: str = Field(..., min_length=1, max_length=50)
    symbols: list[str] = Field(..., min_length=1, max_length=1000)
    dataset_type: str = Field(..., min_length=1, max_length=50)
    timeframe: str = Field("1d", min_length=1, max_length=10)
    exchange: str | None = Field(None, max_length=20)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        for s in v:
            if not (1 <= len(s) <= 20):
                raise ValueError(f"Symbol {s!r} must be 1-20 characters")
        return v


class BackfillRequest(BaseModel):
    """Request body for POST /api/v1/ingest/backfill."""

    provider: str = Field(..., min_length=1, max_length=50)
    symbol: str = Field(..., min_length=1, max_length=20)
    start_date: date
    end_date: date
    timeframe: str = Field("1d", min_length=1, max_length=10)
    chunk_days: int = Field(30, ge=1, le=365)
    exchange: str | None = Field(None, max_length=20)

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        if start and (v - start).days > 10 * 365:
            raise ValueError("Date range must not exceed 10 years")
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


# ---------------------------------------------------------------------------
# EODHD quota admin responses (W3-8)
# ---------------------------------------------------------------------------


class DailyBudgetDetail(BaseModel):
    """Daily sub-budget breakdown within the quota status response."""

    # Credits allotted for today (burst_capacity * safety_factor).
    allotted: int
    # Credits spent today (burst_capacity - remaining_tokens).
    spent: int
    # Headroom ratio: (allotted - spent) / allotted.
    # Positive = within budget; negative = over budget.
    headroom_ratio: float


class CircuitBreakerDetail(BaseModel):
    """Circuit breaker state within the quota status response."""

    # Human-readable state: "closed" | "open" | "half_open".
    state: str
    # Number of times the breaker has tripped today (trips_total is cumulative;
    # this field is always 0 until the circuit-breaker component is wired in).
    trips_today: int


class EodhdQuotaStatusResponse(BaseModel):
    """Response for GET /api/v1/eodhd/quota/status.

    Combines token-bucket quota data with daily-budget and circuit-breaker info.
    """

    provider: str
    # ISO month string, e.g. "2026-04".
    month: str
    # Tokens consumed since last full refill (proxy for credits_used).
    credits_used: int
    # Burst capacity of the token bucket (proxy for monthly_budget).
    monthly_budget: int
    # Percentage of the burst capacity consumed (0.0-100.0+).
    utilization_pct: float
    # Daily sub-budget breakdown.
    daily_budget: DailyBudgetDetail
    # Circuit breaker state (stubbed until the CB component is added).
    circuit_breaker: CircuitBreakerDetail
