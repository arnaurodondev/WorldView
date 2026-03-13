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
    provider: str = ""
    timeframe: str = "1d"
    fetched_at: datetime | None = None
    schema_version: int = field(default=OHLCV_SCHEMA_VERSION, init=False)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalOHLCVBar:
        fetched_at_raw = d.get("fetched_at")
        fetched_at = (
            fetched_at_raw
            if isinstance(fetched_at_raw, datetime)
            else datetime.fromisoformat(str(fetched_at_raw))
            if fetched_at_raw is not None
            else None
        )
        # FIX-O1: normalise separator before parsing (compatible with Python 3.10+).
        # EODHD EOD uses key "date"; intraday uses key "datetime".
        raw_date = d.get("date") or d.get("datetime", "")
        if isinstance(raw_date, datetime):
            bar_date = raw_date
        else:
            bar_date = datetime.fromisoformat(str(raw_date).replace(" ", "T"))

        # adjusted_close: populated only for EOD bars from EODHD (/eod/ endpoint).
        # Intraday bars (/intraday/ endpoint) return no adjusted price — stored as None.
        # This is expected behaviour, not a data quality issue. (FIX-O2)

        return cls(
            symbol=d["symbol"],
            exchange=d["exchange"],
            date=bar_date,
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=int(d["volume"]),
            adjusted_close=float(d["adjusted_close"]) if d.get("adjusted_close") is not None else None,
            source=d.get("source", ""),
            provider=d.get("provider", ""),
            timeframe=d.get("timeframe", "1d"),
            fetched_at=fetched_at,
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
            "provider": self.provider,
            "timeframe": self.timeframe,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at is not None else None,
            "schema_version": self.schema_version,
        }
