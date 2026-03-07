"""Canonical company fundamentals model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from contracts.versions import FUNDAMENTAL_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalFundamentals:
    """Company fundamentals snapshot (annual or quarterly reporting period).

    Uses float for financial values — adequate precision for fundamental ratios.
    """

    symbol: str
    exchange: str
    period: str
    report_date: datetime
    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None
    debt_to_equity: float | None = None
    source: str = ""
    schema_version: int = field(default=FUNDAMENTAL_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalFundamentals:
        return cls(
            symbol=d["symbol"],
            exchange=d["exchange"],
            period=d["period"],
            report_date=(
                d["report_date"]
                if isinstance(d["report_date"], datetime)
                else datetime.fromisoformat(str(d["report_date"]))
            ),
            revenue=float(d["revenue"]) if d.get("revenue") is not None else None,
            net_income=float(d["net_income"]) if d.get("net_income") is not None else None,
            eps=float(d["eps"]) if d.get("eps") is not None else None,
            pe_ratio=float(d["pe_ratio"]) if d.get("pe_ratio") is not None else None,
            market_cap=float(d["market_cap"]) if d.get("market_cap") is not None else None,
            debt_to_equity=float(d["debt_to_equity"]) if d.get("debt_to_equity") is not None else None,
            source=d.get("source", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "period": self.period,
            "report_date": self.report_date.isoformat(),
            "revenue": self.revenue,
            "net_income": self.net_income,
            "eps": self.eps,
            "pe_ratio": self.pe_ratio,
            "market_cap": self.market_cap,
            "debt_to_equity": self.debt_to_equity,
            "source": self.source,
            "schema_version": self.schema_version,
        }
