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

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String, text
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

    # ── Wave L-4a snapshot fields (PLAN-0089, audit 2026-05-28-wave-l4) ────────
    #
    # All four columns are nullable for R11 forward-compat and because the
    # underlying EODHD JSONB sections (analyst_consensus, share_statistics) are
    # sparse: small-cap / foreign listings frequently lack analyst coverage and
    # institutional-holder data.
    #
    # UNIT CONVENTION (documented in writer + extractor):
    #   * ``institutional_ownership_pct`` and ``short_percent`` are stored as
    #     DECIMAL FRACTIONS (e.g. 0.743 = 74.3%, 0.034 = 3.4%) to match the
    #     fcf_margin convention from Wave L-2. The extractor normalises the
    #     two EODHD source fields, which use divergent units (institutional
    #     is already a percent, short is already a fraction).
    #   * ``analyst_consensus_rating`` is stored on the 1-5 scale documented
    #     in the writer (higher = more bullish per task spec; differs from
    #     raw EODHD which is 1=StrongBuy..5=StrongSell, so the extractor
    #     applies a static text→numeric mapping when EODHD returns a string).
    #   * ``analyst_target_price`` is stored in USD (matches EODHD raw).

    # Analyst consensus target price (USD) — EODHD AnalystRatings.TargetPrice
    analyst_target_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # Analyst consensus rating on a 1-5 scale (higher = more bullish per
    # WL-4a task spec). NUMERIC(4,2) accommodates non-integer averages.
    analyst_consensus_rating: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)

    # Institutional ownership as a decimal fraction (e.g. 0.743 = 74.3%).
    # EODHD source field ``SharesStats.PercentInstitutions`` is reported as a
    # percent (e.g. 74.3), so the extractor divides by 100 before storing.
    institutional_ownership_pct: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)

    # Short interest as a decimal fraction of float (e.g. 0.034 = 3.4%).
    # EODHD source field ``SharesStats.ShortPercentOfFloat`` is already a
    # fraction, so the extractor passes it through unchanged.
    short_percent: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)

    # ── Wave L-4b (PLAN-0089 T-WL4B-01): insider rollup ──────────────────────
    # Trailing-90d net dollar value of insider transactions (BUYs positive,
    # SELLs/GIFTs negative). Computed daily by
    # ``application/use_cases/rollup_insider_90d.py`` from rows in the
    # ``insider_transactions`` table. NULL = "no transactions in window OR
    # rollup has not yet run for this instrument".
    insider_net_buy_90d: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)

    # ── Source periodicity tracking (PLAN-0095 T-W1-04, BP-542, migration 020) ──
    # Records which periodicity (QUARTERLY / ANNUAL) the corresponding derived
    # source row came from. Nullable because: (a) rows written before migration
    # 020 stay NULL until next refresh; (b) when the source section is absent
    # from the EODHD payload the corresponding tracking column also stays NULL.
    period_type_income: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_type_cash_flow: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_type_balance: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Wave L-5c calendar fields (PLAN-0089, migration 028) ──────────────────
    #
    # Nullable DATE columns for the "calendar" screener fields. Both stay NULL
    # for most rows until upstream data pipelines populate them:
    #
    #   * ``next_earnings_date`` — populated by the snapshot writer from the
    #     ``earnings_calendar`` table (``MIN(report_date) WHERE report_date
    #     >= CURRENT_DATE``). The L-5b worker that fills earnings_calendar
    #     is deferred, so values stay NULL in the short term.
    #
    #   * ``next_dividend_date`` — populated by the snapshot writer from the
    #     EODHD ``SplitsDividends.DividendDate`` field on every fundamentals
    #     payload (data is available today for dividend-paying equities).
    #
    # Partial BTREE indexes ``ix_ifs_next_earnings_date`` /
    # ``ix_ifs_next_dividend_date`` (migration 028) excluding NULLs make
    # "earnings within N days" range queries cheap.
    next_earnings_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_dividend_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Metadata ──────────────────────────────────────────────────────────────

    # Timestamp of last backfill / upsert for this instrument (UTC)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
