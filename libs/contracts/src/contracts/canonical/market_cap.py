"""Canonical market cap point model (EXT-08)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalMarketCapPoint:
    """A single historical market capitalization observation."""

    symbol: str
    exchange: str
    date: str  # YYYY-MM-DD
    value_usd: float
    source: str
    fetched_at: str

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalMarketCapPoint:
        return cls(
            symbol=d.get("symbol", ""),
            exchange=d.get("exchange", ""),
            date=d.get("date", ""),
            value_usd=float(d.get("value") or d.get("value_usd", 0)),
            source=d.get("source", "eodhd"),
            fetched_at=d.get("fetched_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "date": self.date,
            "value_usd": self.value_usd,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }
