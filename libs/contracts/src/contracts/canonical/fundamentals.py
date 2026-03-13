"""Canonical company fundamentals model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from contracts.versions import FUNDAMENTAL_SCHEMA_VERSION

_SECTION_KEYS = (
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "highlights",
    "valuation_ratios",
    "technicals_snapshot",
    "share_statistics",
    "splits_dividends",
    "analyst_consensus",
    "earnings_history",
    "earnings_trend",
    "earnings_annual_trend",
    "dividend_history",
    "outstanding_shares",
    "company_profile",
    "institutional_holders",
    "fund_holders",
    "insider_transactions_snapshot",
)


@dataclass(frozen=True)
class CanonicalFundamentals:
    """Company fundamentals snapshot.

    Supports two usage modes:

    1. **Summary mode** (legacy / simple providers): populate ``exchange``,
       ``period``, ``report_date`` and the flat financial fields
       (``revenue``, ``net_income``, …).

    2. **Full-section mode** (EODHD and similar): leave the flat fields at
       their ``None`` defaults and populate the section dicts
       (``income_statement``, ``balance_sheet``, …).  The section keys mirror
       the ``_SECTION_HANDLERS`` mapping in the market-data
       ``FundamentalsConsumer`` so downstream processing requires no further
       transformation.

    In both modes ``symbol`` and ``source`` are always required.
    """

    symbol: str
    # --- legacy summary fields (optional in full-section mode) ---
    exchange: str = ""
    period: str = ""
    report_date: datetime | None = None
    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None
    debt_to_equity: float | None = None
    source: str = ""
    # --- full-section fields (populated by EODHD and similar providers) ---
    income_statement: dict[str, Any] | None = None
    balance_sheet: dict[str, Any] | None = None
    cash_flow: dict[str, Any] | None = None
    valuation_ratios: dict[str, Any] | None = None
    technicals_snapshot: dict[str, Any] | None = None
    share_statistics: dict[str, Any] | None = None
    splits_dividends: dict[str, Any] | None = None
    analyst_consensus: dict[str, Any] | None = None
    earnings_history: dict[str, Any] | None = None
    earnings_trend: dict[str, Any] | None = None
    earnings_annual_trend: dict[str, Any] | None = None
    dividend_history: dict[str, Any] | None = None
    outstanding_shares: dict[str, Any] | None = None
    # --- additional section fields (FIX: previously stripped) ---
    highlights: dict[str, Any] | None = None
    company_profile: dict[str, Any] | None = None
    institutional_holders: dict[str, Any] | None = None
    fund_holders: dict[str, Any] | None = None
    insider_transactions_snapshot: dict[str, Any] | None = None
    schema_version: int = field(default=FUNDAMENTAL_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalFundamentals:
        report_date_raw = d.get("report_date")
        if isinstance(report_date_raw, datetime):
            report_date: datetime | None = report_date_raw
        elif report_date_raw is not None:
            report_date = datetime.fromisoformat(str(report_date_raw))
        else:
            report_date = None

        return cls(
            symbol=d["symbol"],
            exchange=d.get("exchange", ""),
            period=d.get("period", ""),
            report_date=report_date,
            revenue=float(d["revenue"]) if d.get("revenue") is not None else None,
            net_income=float(d["net_income"]) if d.get("net_income") is not None else None,
            eps=float(d["eps"]) if d.get("eps") is not None else None,
            pe_ratio=float(d["pe_ratio"]) if d.get("pe_ratio") is not None else None,
            market_cap=float(d["market_cap"]) if d.get("market_cap") is not None else None,
            debt_to_equity=float(d["debt_to_equity"]) if d.get("debt_to_equity") is not None else None,
            source=d.get("source", ""),
            # section fields
            income_statement=d.get("income_statement"),
            balance_sheet=d.get("balance_sheet"),
            cash_flow=d.get("cash_flow"),
            valuation_ratios=d.get("valuation_ratios"),
            technicals_snapshot=d.get("technicals_snapshot"),
            share_statistics=d.get("share_statistics"),
            splits_dividends=d.get("splits_dividends"),
            analyst_consensus=d.get("analyst_consensus"),
            earnings_history=d.get("earnings_history"),
            earnings_trend=d.get("earnings_trend"),
            earnings_annual_trend=d.get("earnings_annual_trend"),
            dividend_history=d.get("dividend_history"),
            outstanding_shares=d.get("outstanding_shares"),
            highlights=d.get("highlights"),
            company_profile=d.get("company_profile"),
            institutional_holders=d.get("institutional_holders"),
            fund_holders=d.get("fund_holders"),
            insider_transactions_snapshot=d.get("insider_transactions_snapshot"),
        )

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "period": self.period,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "revenue": self.revenue,
            "net_income": self.net_income,
            "eps": self.eps,
            "pe_ratio": self.pe_ratio,
            "market_cap": self.market_cap,
            "debt_to_equity": self.debt_to_equity,
            "source": self.source,
            "schema_version": self.schema_version,
        }
        # Include section data only when present (keeps legacy to_dict output stable)
        for key in _SECTION_KEYS:
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        return d
