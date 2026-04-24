"""Canonical PriceSnapshot model — cross-service contract for resolved price data.

A PriceSnapshot is the result of the fallback resolution chain:
  fresh quote → bulk quote → intraday bar → daily bar → stale cache → unavailable.

It carries not just the price but also provenance (PriceSource), data quality
(FreshnessStatus), and refresh eligibility so consumers can make informed UI
decisions without duplicating staleness logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class PriceSource(StrEnum):
    """Which data source provided the resolved price, in priority order."""

    # Live quote from the quotes table, age < 5 min (real-time feed)
    FRESH_QUOTE = "fresh_quote"
    # Quote from the quotes table, age 5-15 min (bulk-refresh or slightly stale feed)
    BULK_QUOTE = "bulk_quote"
    # Close price of the most recent 5-minute OHLCV bar
    INTRADAY_5M_CLOSE = "intraday_5m_close"
    # Close price of the most recent 1-hour OHLCV bar
    INTRADAY_1H_CLOSE = "intraday_1h_close"
    # Close price of the most recent daily OHLCV bar (EOD)
    DAILY_CLOSE = "daily_close"
    # A prior PriceSnapshot retrieved from Valkey that has since expired
    STALE_SNAPSHOT = "stale_snapshot"
    # No price data available from any source
    UNAVAILABLE = "unavailable"


class FreshnessStatus(StrEnum):
    """Human-readable staleness classification for UI display and alerting."""

    # Within 5 min during market hours, OR a daily close outside market hours
    # (daily close IS the authoritative live price when markets are shut)
    LIVE = "live"
    # Within 1 hour — acceptable for most portfolio views
    RECENT = "recent"
    # Within 1 day — acceptable for end-of-day analytics
    DELAYED = "delayed"
    # Older than 1 day — shown with explicit staleness warning in UI
    STALE = "stale"
    # No price data whatsoever — instrument may be delisted or never ingested
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PriceSnapshot:
    """Resolved, sourced, and freshness-classified price for a single instrument.

    This is the canonical cross-service representation.  It is stored in Valkey
    by the market-data service and consumed by S9 (api-gateway) to serve
    frontend price requests without hitting the DB on every render.

    Attributes:
        instrument_id:  UUIDv7 of the Instrument record in market-data DB.
        symbol:         Ticker symbol (e.g. "AAPL").
        exchange:       Exchange code (e.g. "NASDAQ", "CC" for crypto).
        price:          Resolved price as Decimal — never None (UNAVAILABLE uses 0).
        price_change:   Absolute change vs previous close, or None if unknown.
        price_change_pct: Percentage change vs previous close, or None if unknown.
        timestamp:      UTC datetime when the underlying price data was valid.
        fetched_at:     UTC datetime when this snapshot was resolved.
        source:         Which fallback step produced this price.
        freshness_status: Staleness classification, market-hours-aware.
        stale_reason:   Human-readable explanation when status is STALE/UNAVAILABLE.
        refresh_available: Whether a fresh quote can be triggered (rate-limit aware).
        refresh_cooldown_remaining_sec: Seconds until next refresh is allowed.
    """

    instrument_id: str
    symbol: str
    exchange: str
    price: Decimal
    price_change: Decimal | None  # vs previous close; None if data unavailable
    price_change_pct: Decimal | None  # percentage form; None if data unavailable
    timestamp: datetime  # UTC — when price was valid
    fetched_at: datetime  # UTC — when snapshot was resolved
    source: PriceSource
    freshness_status: FreshnessStatus
    stale_reason: str | None
    refresh_available: bool = True
    refresh_cooldown_remaining_sec: int = 0

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict for Valkey storage."""
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "price": str(self.price),
            "price_change": str(self.price_change) if self.price_change is not None else None,
            "price_change_pct": str(self.price_change_pct) if self.price_change_pct is not None else None,
            "timestamp": self.timestamp.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "source": self.source,
            "freshness_status": self.freshness_status,
            "stale_reason": self.stale_reason,
            "refresh_available": self.refresh_available,
            "refresh_cooldown_remaining_sec": self.refresh_cooldown_remaining_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PriceSnapshot:
        """Deserialise from the dict produced by ``to_dict()``."""
        return cls(
            instrument_id=d["instrument_id"],
            symbol=d["symbol"],
            exchange=d["exchange"],
            price=Decimal(d["price"]),
            price_change=Decimal(d["price_change"]) if d.get("price_change") is not None else None,
            price_change_pct=Decimal(d["price_change_pct"]) if d.get("price_change_pct") is not None else None,
            timestamp=datetime.fromisoformat(d["timestamp"]),
            fetched_at=datetime.fromisoformat(d["fetched_at"]),
            source=PriceSource(d["source"]),
            freshness_status=FreshnessStatus(d["freshness_status"]),
            stale_reason=d.get("stale_reason"),
            refresh_available=d.get("refresh_available", True),
            refresh_cooldown_remaining_sec=d.get("refresh_cooldown_remaining_sec", 0),
        )
