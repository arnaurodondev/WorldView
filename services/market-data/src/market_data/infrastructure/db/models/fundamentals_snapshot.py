"""ORM model for the ``instrument_fundamentals_snapshot`` table.

WHY THIS MODEL EXISTS: Provides a typed, single-row-per-instrument snapshot
of the key display metrics needed by InstrumentKeyMetrics and FundamentalsTab.
The existing ``fundamental_metrics`` table stores key-value pairs optimised for
screener and timeseries queries; this table is optimised for single-instrument
frontend reads (one SELECT = one row = all 10 display metrics).

Wave D (PLAN-0050): eps_ttm, beta, avg_volume_30d, operating_cash_flow,
capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda,
credit_rating.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class InstrumentFundamentalsSnapshotModel(Base):
    """Single-row snapshot of key fundamentals metrics for one instrument.

    All metric columns are nullable — NULL means "data not yet available".
    The ``updated_at`` column allows the backfill script to detect stale rows.
    """

    __tablename__ = "instrument_fundamentals_snapshot"

    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    # ── EODHD-sourced fields ──────────────────────────────────────────────────

    # Earnings per share (trailing twelve months) — EODHD Highlights.EarningsShare
    eps_ttm: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)

    # Market beta (52-week, vs S&P 500) — EODHD Technicals.Beta
    beta: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    # 30-day average daily volume — EODHD Technicals.200DayMA area (share_statistics)
    # EODHD does not expose a direct avg_volume_30d field; we use ShareStatistics
    # or derive from OHLCV bars when available.
    avg_volume_30d: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Operating cash flow (USD) — most recent annual — EODHD CashFlow statement
    operating_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)

    # Capital expenditures (USD, stored as negative in EODHD CashFlow statements)
    capex: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)

    # ── Derived fields (computed by backfill script) ───────────────────────────

    # Free cash flow = operating_cf - |capex|
    free_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)

    # FCF margin = fcf / revenue (NULL if revenue = 0)
    fcf_margin: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Interest coverage = EBIT / interest_expense (NULL if interest_expense = 0)
    interest_coverage: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Net debt / EBITDA = (total_debt - cash) / ebitda (NULL if ebitda ≤ 0)
    net_debt_to_ebitda: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Credit rating string — e.g. "A+", "BBB", "BB-" — from EODHD CreditRating
    credit_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── Metadata ──────────────────────────────────────────────────────────────

    # Timestamp of last backfill / upsert for this instrument (UTC)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
