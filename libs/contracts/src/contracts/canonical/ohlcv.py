"""Canonical OHLCV bar model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from contracts.versions import OHLCV_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalOHLCVBar:
    """Open-High-Low-Close-Volume bar for a single instrument on a single date."""

    symbol: str
    exchange: str
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: float | None = None
    source: str = ""
    schema_version: int = field(default=OHLCV_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalOHLCVBar:
        return cls(
            symbol=d["symbol"],
            exchange=d["exchange"],
            date=d["date"] if isinstance(d["date"], datetime) else datetime.fromisoformat(str(d["date"])),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=int(d["volume"]),
            adjusted_close=float(d["adjusted_close"]) if d.get("adjusted_close") is not None else None,
            source=d.get("source", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "date": self.date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "adjusted_close": self.adjusted_close,
            "source": self.source,
            "schema_version": self.schema_version,
        }
