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
    # ── Wave L-3: computed OHLCV-derived metric ranges ───────────────────────
    # Shorthand for "filter on the latest value of the computed metric in
    # fundamental_metrics with period_type=SNAPSHOT, section=computed_returns".
    # The router expands each populated *_min/*_max pair into an existing
    # ScreenFilter(metric=<name>, min_value=..., max_value=...) so the existing
    # latest-value-per-instrument JOIN handles them — no new SQL shape needed.
    # All values are fractions (NOT percent), matching the worker output convention.
    dist_from_52w_high_pct_min: float | None = None
    dist_from_52w_high_pct_max: float | None = None
    dist_from_52w_low_pct_min: float | None = None
    dist_from_52w_low_pct_max: float | None = None
    return_1m_min: float | None = None
    return_1m_max: float | None = None
    return_3m_min: float | None = None
    return_3m_max: float | None = None
    return_6m_min: float | None = None
    return_6m_max: float | None = None
    return_ytd_min: float | None = None
    return_ytd_max: float | None = None
    return_1y_min: float | None = None
    return_1y_max: float | None = None
    return_3y_min: float | None = None
    return_3y_max: float | None = None


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
