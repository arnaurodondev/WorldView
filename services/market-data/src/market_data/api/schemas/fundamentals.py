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


class FundamentalsSnapshotResponse(BaseModel):
    """Flat one-row snapshot of 10 key derived metrics for an instrument.

    WHY THIS SCHEMA: The FundamentalsTab and InstrumentKeyMetrics panel need
    eps_ttm, beta, avg_volume_30d, and 7 derived metrics (FCF, interest
    coverage, etc.) in a single typed response.  Unlike the raw section
    records (FundamentalsResponse), this response has known field names and
    types — no JSONB key-hunting required in the frontend.

    All fields are nullable: NULL means "data not yet available" for this
    instrument (e.g. ETFs with no cash flow statements, newly-listed stocks
    without EODHD fundamentals coverage).
    """

    instrument_id: str
    # EPS (trailing twelve months) from EODHD Highlights
    eps_ttm: float | None = None
    # Market beta (52-week, vs S&P 500) from EODHD Technicals
    beta: float | None = None
    # 30-day average daily volume from EODHD Technicals / ShareStatistics
    avg_volume_30d: int | None = None
    # Cash flow statement fields (most recent annual)
    operating_cash_flow: float | None = None
    capex: float | None = None
    # Derived: free_cash_flow = operating_cf - |capex|
    free_cash_flow: float | None = None
    # Derived: fcf_margin = fcf / revenue (NULL if revenue = 0)
    fcf_margin: float | None = None
    # Derived: interest_coverage = ebit / interest_expense
    interest_coverage: float | None = None
    # Derived: net_debt_to_ebitda = (total_debt - cash) / ebitda
    net_debt_to_ebitda: float | None = None
    # Credit rating string (e.g. "A+", "BBB-")
    credit_rating: str | None = None
    # Timestamp of the last backfill run that produced this row
    updated_at: str | None = None


# ── PLAN-0066 Wave G: temporal RAG endpoint schemas ────────────────────────────


class FundamentalsHistoryPeriod(BaseModel):
    """One reporting period in the fundamentals history response.

    WHY nullable fields: not all EODHD earnings records carry income-statement
    data (earnings_history section contains EPS/surprise; revenue/gross_profit/
    net_income come from the income_statement section joined on period_end).
    pe_ratio and market_cap are TTM figures from the highlights snapshot.
    """

    period: str  # human-readable label, e.g. "Q1 2026"
    period_end_date: str  # "YYYY-MM-DD"
    revenue: float | None = None
    gross_profit: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None


class FundamentalsHistoryResponse(BaseModel):
    """Response for GET /api/v1/fundamentals/history (temporal RAG PLAN-0066 Wave G)."""

    instrument_id: str
    ticker: str
    periods: list[FundamentalsHistoryPeriod]
    period_count: int
