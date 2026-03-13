"""Canonical yield curve point model (EXT-07)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalYieldPoint:
    """A single maturity rate observation from the US Treasury yield curve."""

    series: str  # "yield" | "bill" | "longterm"
    date: str  # YYYY-MM-DD
    maturity: str  # "1_month", "10_year", etc.
    rate: float | None  # percent, e.g. 4.2350
    source: str
    fetched_at: str

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalYieldPoint:
        rate_raw = d.get("rate")
        rate = float(rate_raw) if rate_raw is not None else None
        return cls(
            series=d.get("series", ""),
            date=d.get("date", ""),
            maturity=d.get("maturity", ""),
            rate=rate,
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "series": self.series,
            "date": self.date,
            "maturity": self.maturity,
            "rate": self.rate,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }
