"""Pydantic schemas for fundamental_metrics API (timeseries + screening)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class MetricDataPointResponse(BaseModel):
    """A single timeseries data point."""

    as_of_date: date
    value_numeric: float | None = None
    value_text: str | None = None
    period_type: str | None = None


class TimeseriesResponse(BaseModel):
    """Timeseries data for a single instrument + metric."""

    instrument_id: str
    metric: str
    data: list[MetricDataPointResponse]


class ScreenFilterRequest(BaseModel):
    """A single metric filter for screening."""

    metric: str = Field(..., pattern=r"^[a-z_][a-z0-9_]{0,63}$")
    min_value: float | None = None
    max_value: float | None = None
    period_type: str | None = None
    sector: str | None = None
    # FIX-LIVE-M (2026-05-24): GICS industry filter (e.g. "Semiconductors").
    # Sector alone is too broad for queries like "AI chip companies".
    industry: str | None = None
    # Wave L-1: instrument-attribute filters (applied as WHERE on instruments table)
    country: str | None = None
    exchange: str | None = None
    has_fundamentals: bool | None = None
    has_ohlcv: bool | None = None
    # ── Wave L-2: instrument_fundamentals_snapshot column filters ────────────
    # All fields are optional/default-None for R11 forward-compatibility.
    # Numeric min/max are inclusive ranges; credit_ratings is an IN list.
    # Mirrors ScreenFilter port (application/ports/repositories.py).
    avg_volume_30d_min: float | None = None
    avg_volume_30d_max: float | None = None
    eps_ttm_min: float | None = None
    eps_ttm_max: float | None = None
    free_cash_flow_min: float | None = None
    free_cash_flow_max: float | None = None
    fcf_margin_min: float | None = None
    fcf_margin_max: float | None = None
    interest_coverage_min: float | None = None
    interest_coverage_max: float | None = None
    net_debt_to_ebitda_min: float | None = None
    net_debt_to_ebitda_max: float | None = None
    credit_ratings: list[str] | None = None
    # ── Wave L-4a snapshot column filters (PLAN-0089) ────────────────────────
    # Mirror of ScreenFilter port fields. Decimal-fraction unit convention
    # applies to ownership and short (e.g. 0.5 means 50%) — see port docs.
    analyst_target_price_min: float | None = None
    analyst_target_price_max: float | None = None
    analyst_consensus_rating_min: float | None = None
    analyst_consensus_rating_max: float | None = None
    institutional_ownership_pct_min: float | None = None
    institutional_ownership_pct_max: float | None = None
    short_percent_min: float | None = None
    short_percent_max: float | None = None
    # ── Wave L-5c: calendar (date) field filters ─────────────────────────────
    # Expressed as "within next N days" because a UI calendar-style range picker
    # is much heavier than a single number-of-days input — and "earnings within
    # 30 days" / "dividend within 14 days" maps cleanly to range queries:
    #     WHERE col BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL ':n days'
    # Validation: ge=0 disallows negative windows (would be past-only, better
    # served by the dedicated calendar endpoints); le=365 caps at a year to
    # keep query plans selective and the partial index useful.
    next_earnings_within_days: int | None = Field(default=None, ge=0, le=365)
    next_dividend_within_days: int | None = Field(default=None, ge=0, le=365)


class ScreenRequest(BaseModel):
    """Screening request body (PRD-0017 §6.8, NFR-001).

    Breaking change from prior version: limit max reduced 1000→200, default 100→50;
    offset max tightened to 5000. Coordinate with API consumers before deploying.
    """

    # WHY min_length=0 (was 1): empty filters activates the optimised "no filter" path in
    # query_screen which uses LEFT JOINs to return all key display metrics for every instrument.
    # The min_length=1 constraint forced callers to send a fallback filter (e.g. market_cap≥0)
    # which triggered the INNER JOIN path and only returned that one metric — causing all other
    # screener columns to show "—". Removing the lower bound lets the BFF send [] when the
    # user has no active filters, surfacing pe_ratio/beta/etc. in the default view.
    filters: list[ScreenFilterRequest] = Field(default=[], max_length=20)
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0, le=5000)
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "asc"


class ScreenInstrumentResponse(BaseModel):
    """One instrument matching screen criteria."""

    instrument_id: str
    ticker: str | None = None
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    # WHY float | str | None: numeric metrics are float; credit_rating is a string.
    metrics: dict[str, float | str | None]


class ScreenResponse(BaseModel):
    """Screening results."""

    results: list[ScreenInstrumentResponse]
    count: int
    total: int


class AvailableMetricsResponse(BaseModel):
    """List of metric names available for an instrument."""

    instrument_id: str
    metrics: list[str]


class ScreenFieldResponse(BaseModel):
    """Metadata for a single screenable fundamental metric field (PRD-0017 §6.2)."""

    name: str
    label: str
    type: str
    unit: str | None = None
    description: str | None = None
    observed_min: float | None = None
    observed_max: float | None = None
    null_fraction: float


class ScreenFieldsResponse(BaseModel):
    """Response for GET /fundamentals/screen/fields."""

    fields: list[ScreenFieldResponse]
