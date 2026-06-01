"""Pydantic schemas for fundamentals API responses."""

from __future__ import annotations

from datetime import date, datetime
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
    # F-LIVE-P (2026-05-26): explicit periodicity label per row. The use case
    # filters the SQL to a single period_type, so by construction every row
    # in a single response shares the same value. Exposing it here lets the
    # rag-chat tool layer surface the contract to the LLM (BP-577 defense).
    period_type: str = "QUARTERLY"
    revenue: float | None = None
    gross_profit: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None


# PLAN-0103 W25 / BP-640: snapshot-vs-period-row P/E injection fix.
# WHY a SIBLING field (not per-row): the EODHD HIGHLIGHTS section is a single
# TTM/live valuation snapshot (one current PERatio + MarketCapitalization +
# EV/EBITDA + ...), not a per-period stream. Pre-W25 the use case injected
# ``pe_ratio`` and ``market_cap`` into EVERY period row, so the LLM either
# (a) confidently quoted the TTM P/E as if it were the row's quarterly P/E
# (fabrication), or (b) refused because the per-period cell looked empty in
# its own mental model. Surfacing the snapshot once, with an explicit
# ``as_of`` date and source, lets the LLM cleanly separate "current P/E"
# answers (read snapshot) from "quarterly trend" answers (read periods).
#
# All fields are nullable: not every issuer reports every ratio (e.g. ETFs
# rarely surface a PERatio; tiny-cap stocks omit EV/EBITDA). A missing
# ``as_of`` falls back to ``None`` — the renderer can then either omit the
# block entirely or label it "as-of date unknown".
class CurrentSnapshot(BaseModel):
    """Single live-valuation snapshot drawn from EODHD HIGHLIGHTS.

    Mirrors the as-of-today TTM block on the API page. Separate from
    ``FundamentalsHistoryPeriod`` because the snapshot semantics (current
    valuation) are fundamentally different from period semantics (historical
    operating metrics). See BP-640 / PLAN-0103 W25.
    """

    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    market_cap_usd: float | None = None
    price_to_book: float | None = None
    dividend_yield: float | None = None
    # ISO date of the snapshot row in the HIGHLIGHTS section. None when the
    # use case could not resolve a definitive ``period_end`` for the most
    # recent highlights record.
    as_of: date | None = None
    # Provenance marker so the LLM (and the rag-chat handler) can cite the
    # source verbatim. Always ``"highlights"`` today; reserved field for
    # forward compatibility with a future blended snapshot.
    source: str = "highlights"


class FundamentalsHistoryResponse(BaseModel):
    """Response for GET /api/v1/fundamentals/history (temporal RAG PLAN-0066 Wave G).

    PLAN-0103 W25 / BP-640: now exposes ``current_snapshot`` (CurrentSnapshot |
    None) as a SIBLING of ``periods``. The snapshot holds the TTM/live
    valuation metrics that previously bled into every period row. Periods
    keep flow/operating metrics ONLY. None when no HIGHLIGHTS record exists
    for the instrument.
    """

    instrument_id: str
    ticker: str
    periods: list[FundamentalsHistoryPeriod]
    period_count: int
    current_snapshot: CurrentSnapshot | None = None


# PLAN-0095 W2 T-W2-01: batch fundamentals history.
# WHY a batch endpoint: rag-chat's screener → fundamentals workflow currently
# fans out N sequential ``get_fundamentals_history`` tool calls through the
# LLM. Each turn is a ~7-8 s LLM round-trip plus a use-case query; for 5
# tickers that's 5 turns. A single batch tool call collapses that into one
# turn so the LLM never has to deliberate between successive fundamentals
# pulls — measured 5-10x latency reduction on agg_q6.
class FundamentalsBatchRequest(BaseModel):
    """Request body for POST /v1/fundamentals/batch.

    ``tickers`` is capped at 25 entries to bound worst-case fan-out latency
    (25 concurrent ``GetFundamentalsHistoryUseCase.execute`` calls per request);
    requests above the cap return HTTP 422 from the route's manual length check.
    """

    tickers: list[str]
    periods: int = 5


class FundamentalsBatchPerTickerResult(BaseModel):
    """Per-ticker result inside a batch response.

    ``status="ok"`` populates ``periods`` (and leaves ``reason`` as ``None``);
    ``status="error"`` populates ``reason`` (and leaves ``periods`` as ``None``).
    Per-ticker failures NEVER fail the overall batch — see ``return_exceptions=True``
    in the route handler. The shape is intentionally flat so callers can iterate
    ``response.results.items()`` without branching on missing keys.

    PLAN-0103 W25 / BP-640: ``current_snapshot`` mirrors the singular endpoint's
    new sibling field so multi-ticker LLM workflows can surface live valuation
    ratios without a second HTTP round-trip.
    """

    status: str  # Literal["ok", "error"] — kept str for FastAPI/OpenAPI simplicity
    periods: list[FundamentalsHistoryPeriod] | None = None
    reason: str | None = None
    current_snapshot: CurrentSnapshot | None = None


class FundamentalsBatchResponse(BaseModel):
    """Response for POST /v1/fundamentals/batch.

    ``results`` is keyed by the ORIGINAL ticker the caller supplied (preserves
    case so the caller can correlate with its own state) — NOT by the canonical
    instrument symbol returned from the lookup use case.
    """

    results: dict[str, FundamentalsBatchPerTickerResult]
