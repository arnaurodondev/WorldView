"""Canonical quote model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from contracts.versions import QUOTE_SCHEMA_VERSION


@dataclass(frozen=True)
class CanonicalQuote:
    """Real-time or delayed quote snapshot for a single instrument.

    Uses float for price fields — see ohlcv.py for the float vs Decimal rationale.
    """

    symbol: str
    exchange: str
    bid: float | None
    ask: float | None
    last: float | None
    volume: int | None
    timestamp: datetime
    bid_size: int | None = None
    ask_size: int | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    prev_close: float | None = None
    source: str = ""
    schema_version: int = field(default=QUOTE_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalQuote:
        return cls(
            symbol=d["symbol"],
            exchange=d["exchange"],
            bid=float(d["bid"]) if d.get("bid") is not None else None,
            ask=float(d["ask"]) if d.get("ask") is not None else None,
            last=float(d["last"]) if d.get("last") is not None else None,
            volume=int(d["volume"]) if d.get("volume") is not None else None,
            timestamp=(
                d["timestamp"] if isinstance(d["timestamp"], datetime) else datetime.fromisoformat(str(d["timestamp"]))
            ),
            bid_size=int(d["bid_size"]) if d.get("bid_size") is not None else None,
            ask_size=int(d["ask_size"]) if d.get("ask_size") is not None else None,
            high=float(d["high"]) if d.get("high") is not None else None,
            low=float(d["low"]) if d.get("low") is not None else None,
            open=float(d["open"]) if d.get("open") is not None else None,
            prev_close=float(d["prev_close"]) if d.get("prev_close") is not None else None,
            source=d.get("source", ""),
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "high": self.high,
            "low": self.low,
            "open": self.open,
            "prev_close": self.prev_close,
            "source": self.source,
            "schema_version": self.schema_version,
        }
