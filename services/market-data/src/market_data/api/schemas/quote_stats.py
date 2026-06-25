"""Pydantic schemas for the Quote-tab statistics endpoints (B-Q-2/3/4).

Wire format for:
  GET /api/v1/instruments/{id}/intraday-stats
  GET /api/v1/instruments/{id}/returns
  GET /api/v1/instruments/{id}/price-levels

All numeric statistics are nullable floats: ``null`` means "insufficient
history / no data" — the use cases never fabricate values (see
``query_quote_stats.py`` honesty contract). Floats (not Decimal strings) are
used because these are display statistics, not accounting values.
"""

from __future__ import annotations

from pydantic import BaseModel


class IntradayStatsResponse(BaseModel):
    """Current-session statistics (B-Q-2)."""

    instrument_id: str
    # ISO date of the session the stats describe (most recent 1d bar); null
    # when the instrument has no daily bars at all.
    session_date: str | None
    open: float | None
    prev_close: float | None
    day_high: float | None
    day_low: float | None
    # Volume-weighted average price from intraday bars ("1m" preferred, "5m"
    # fallback — see vwap_source). Null when no intraday bars with volume exist.
    vwap: float | None
    vwap_source: str | None  # "1m" | "5m" | null
    volume: int | None
    # Session volume / mean volume of the prior 30 sessions. >1 = heavier than
    # usual. Null when either side of the ratio is unavailable.
    volume_vs_30d_ratio: float | None


class MultiPeriodReturnsResponse(BaseModel):
    """Close-on-close % returns over standard anchors (B-Q-3).

    ``returns`` always contains all 9 keys (1D/1W/1M/3M/6M/YTD/1Y/3Y/5Y);
    a key maps to null when the instrument lacks history that far back.
    """

    instrument_id: str
    as_of: str | None  # ISO date of the last daily close used
    returns: dict[str, float | None]


class PriceLevelsResponse(BaseModel):
    """52-week range, moving averages, prior session and simple S/R (B-Q-4)."""

    instrument_id: str
    as_of: str | None
    last_close: float | None
    # 52-week extremes — null when fewer than ~190 sessions of history exist
    # (an honest 52w range needs most of a trading year).
    high_52w: float | None
    low_52w: float | None
    # % distance of last_close from each extreme (negative = below the high).
    pct_from_52w_high: float | None
    pct_from_52w_low: float | None
    ma_50: float | None
    ma_200: float | None
    prior_session_high: float | None
    prior_session_low: float | None
    # Nearest-first swing-point levels (see sr_method for how they're derived).
    support: list[float]
    resistance: list[float]
    # Human-readable description of the S/R derivation — keeps the method
    # transparent to the UI/user instead of pretending it's a trading signal.
    sr_method: str
