"""Freshness TTL constants for the pre-fetch gate in ScheduleDueTasksUseCase.

A watermark is considered "fresh" when ``last_success_at`` is within the TTL for
its dataset type.  Tasks whose watermarks are still fresh are skipped by the
scheduler, preventing redundant EODHD calls.

Values are intentionally conservative (shorter than the poll interval) to allow
for clock skew and processing latency without causing data gaps.

EODHD endpoint credit costs are also declared here so that both the scheduler
(budget filtering) and the execute-task use case (quota consumption) use the same
authoritative values.

Sources
-------
- Freshness TTLs: PLAN-0036 §9.4
- Credit costs:   https://eodhd.com/financial-apis/api-limits
"""

from __future__ import annotations

# ── Pre-fetch freshness TTLs (seconds) ────────────────────────────────────────
# The scheduler skips enqueuing a task if the watermark's last_success_at is
# younger than these values.  0 = never skip (always enqueue on schedule).

FRESHNESS_TTL_SECONDS: dict[str, int] = {
    "quotes": 240,  # 4 min (T0 5-min interval with 1-min tolerance)
    "bulk_quotes": 240,  # same as quotes (bulk = same cadence, different HTTP shape)
    "ohlcv": 82_800,  # 23h  (daily bar available by 17:00 ET)
    "intraday_5m": 240,  # 4 min
    "intraday_1h": 3_300,  # 55 min
    "fundamentals": 518_400,  # 6 days  (refreshed quarterly → large TTL)
    "macro_indicator": 7_689_600,  # 89 days
    "economic_events": 7_689_600,  # 89 days
    "earnings_calendar": 82_800,  # 23h
    "news_sentiment": 82_800,  # 23h
    "insider_transactions": 82_800,
    "yield_curve": 82_800,
    "market_cap": 82_800,
}

# ── EODHD endpoint credit costs ───────────────────────────────────────────────
# Source: https://eodhd.com/financial-apis/api-limits
# These must match the values in schedule_tasks.py._EODHD_CREDIT_COST.

EODHD_CREDIT_COST: dict[str, int] = {
    "fundamentals": 10,  # /api/fundamentals/:ticker
    "ohlcv": 1,  # /api/eod/:ticker
    # /api/eod-bulk-last-day/:EXCHANGE — ONE call returns EVERY symbol on the
    # exchange (correct consolidated volume + adjusted_close). Costs a flat 100
    # credits per exchange regardless of symbol count (verified against
    # https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends). This is
    # ~200x cheaper than 1-credit-per-ticker intraday polling and cheaper than a
    # per-ticker /eod sweep once an exchange has >100 symbols.
    "bulk_eod": 100,
    "quotes": 1,  # /api/real-time/:ticker
    "bulk_quotes": 1,  # /api/real-time/:ticker?s=... — 1 credit per symbol
    "news_sentiment": 5,  # /api/news
    "earnings_calendar": 1,
    "economic_events": 5,  # /api/economic-events
    "macro_indicator": 5,  # /api/macro-indicator
    "insider_transactions": 1,
    "yield_curve": 1,
    "market_cap": 1,
}

# Intraday endpoints (/api/intraday) cost 5 credits each regardless of interval.
EODHD_INTRADAY_COST: int = 5

# Timeframes that hit /api/intraday (5 credits each).
INTRADAY_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "1h"})
