"""Canonical earnings calendar event model (EXT-02)."""

from __future__ import annotations

from dataclasses import dataclass


def _to_float(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class CanonicalEarningsEvent:
    """A single earnings report event (upcoming or historical)."""

    symbol: str
    report_date: str  # YYYY-MM-DD — the date the report is/was released
    fiscal_date_ending: str  # YYYY-MM-DD — the quarter/year end date
    before_after_market: str  # "BeforeMarket" | "AfterMarket" | ""
    currency: str
    eps_estimate: float | None
    eps_actual: float | None
    source: str
    fetched_at: str

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalEarningsEvent:
        return cls(
            symbol=d.get("code", ""),
            report_date=d.get("report_date") or d.get("date", ""),
            fiscal_date_ending=d.get("date", ""),
            before_after_market=d.get("before_after_market") or "",
            currency=d.get("currency") or "",
            eps_estimate=_to_float(d.get("estimate")),
            eps_actual=_to_float(d.get("actual")),
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "report_date": self.report_date,
            "fiscal_date_ending": self.fiscal_date_ending,
            "before_after_market": self.before_after_market,
            "currency": self.currency,
            "eps_estimate": self.eps_estimate,
            "eps_actual": self.eps_actual,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }
