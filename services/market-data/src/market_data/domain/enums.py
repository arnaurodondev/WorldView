"""Domain enumerations for the market-data service."""

from __future__ import annotations

from enum import StrEnum


class Timeframe(StrEnum):
    """OHLCV bar timeframe granularity."""

    ONE_MIN = "1m"
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    THIRTY_MIN = "30m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    ONE_MONTH = "1M"


class DatasetType(StrEnum):
    """Type of canonical dataset stored in object storage."""

    OHLCV = "OHLCV"
    QUOTE = "QUOTE"
    FUNDAMENTALS = "FUNDAMENTALS"


# Provider priority: higher integer = preferred source for conflict resolution.
#
# OHLCV-SOURCING REWORK (2026-06-17): the source identifiers actually emitted by
# the upstream market-ingestion (S4) pipeline are ``alpaca`` (intraday 1m, the
# single source of truth), ``yahoo_finance`` (deep daily, free/keyless) and
# ``eodhd`` (last-resort daily failover) — NOT the legacy ``polygon``/``yahoo``
# placeholders.  Before this fix every one of those strings failed ``Provider(...)``
# construction in the S3 consumer and silently collapsed to ``UNKNOWN`` (priority
# 0), so the ``WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority``
# upsert guard degenerated to "0 >= 0 = always overwrite" — i.e. provider-priority
# conflict resolution was effectively disabled and a late EODHD tick could clobber
# a higher-quality Yahoo/derived bar (the NVDA eodhd<->derived flip-flop).
#
# Priority ladder (higher wins). FINAL TOPOLOGY (PLAN-0036, 2026-06-16): Alpaca is
# the single source for intraday (1m → derived 5m..4h) AND was the polled daily
# source (1Day, ~6y split-adjusted).
#
# DAILY-VOLUME CORRECTION (2026-07-16): Alpaca's free IEX daily feed is WRONG for
# daily bars — its daily ``volume`` is IEX-only (~5% of true consolidated, ~19-30x
# understated) and it carries NO ``adjusted_close`` (the ``_normalize_bars`` mapper
# drops it). Close *price* is fine, but volume + adjusted_close are not. EODHD's
# bulk end-of-day feed (``/eod-bulk-last-day/{EXCHANGE}`` — one call per exchange,
# ~100 credits/day) carries the CORRECT consolidated volume + adjusted_close + raw
# close for every symbol. So a NEW authoritative daily source ``eodhd_bulk`` is
# introduced at priority 120 — ABOVE Alpaca (110) — so the correct EODHD-bulk daily
# bar wins the ``provider_priority >=`` upsert guard over Alpaca's IEX daily bar.
# Alpaca STAYS the intraday 1m source (unchanged) and remains a daily fallback
# (110) if the once-daily bulk CronJob fails. Plain ``eodhd`` (60) stays the
# per-ticker deep-history/failover source. Coordinates with ``fix/ohlcv-dup-bars``:
# that branch normalizes daily ``bar_date`` to UTC-midnight so the eodhd_bulk (120)
# and Alpaca (110) daily bars collapse onto the SAME conflict key and the priority
# guard actually fires; migration 045 dedups ``ORDER BY provider_priority DESC``,
# so eodhd_bulk (120) is the retained winner once its rows exist.
#
# Yahoo Finance is DROPPED from OHLCV routing — its entries remain only so any
# historical ``yahoo_finance`` rows still compare consistently; nothing new is
# routed to Yahoo.
_PROVIDER_PRIORITIES: dict[str, int] = {
    "eodhd_bulk": 120,  # authoritative daily EOD (bulk-last-day) — correct volume + adjusted_close
    "alpaca": 110,  # 1m intraday (source of truth) + polled 1Day daily fallback
    "derived": 110,  # locally-derived (from Alpaca 1m) — authoritative for covered intraday window
    "polygon": 100,  # alternate intraday provider (registered only when keyed)
    "yahoo_finance": 80,  # DROPPED from routing — historical rows only
    "yahoo": 80,  # legacy alias — kept so historical rows compare consistently
    "eodhd": 60,  # per-ticker deep-history / failover daily (Alpaca-1Day / eodhd_bulk primary)
    "alpha_vantage": 40,
    "macrotrends": 20,
    "unknown": 0,
}


class Provider(StrEnum):
    """Data provider identifiers, in descending priority order.

    Values MUST match the ``source`` / event ``provider`` strings emitted by
    market-ingestion (S4) so that ``Provider(provider_str)`` in the S3 consumer
    resolves to a real priority instead of falling through to ``UNKNOWN``.
    """

    EODHD_BULK = "eodhd_bulk"  # authoritative daily EOD via bulk-last-day (priority 120)
    ALPACA = "alpaca"
    DERIVED = "derived"
    POLYGON = "polygon"
    YAHOO_FINANCE = "yahoo_finance"
    YAHOO = "yahoo"  # legacy alias
    EODHD = "eodhd"
    ALPHA_VANTAGE = "alpha_vantage"
    MACROTRENDS = "macrotrends"
    UNKNOWN = "unknown"

    @property
    def priority(self) -> int:
        """Numeric priority for this provider (higher = preferred)."""
        return _PROVIDER_PRIORITIES.get(self.value, 0)


class PeriodType(StrEnum):
    """Reporting period granularity for fundamentals data."""

    ANNUAL = "ANNUAL"
    QUARTERLY = "QUARTERLY"
    SNAPSHOT = "SNAPSHOT"  # point-in-time sections with no fiscal period (FIX-F2)


class FundamentalsSection(StrEnum):
    """Logical sections of a company's fundamentals snapshot."""

    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    HIGHLIGHTS = "highlights"  # FIX-F10: split from valuation_ratios
    VALUATION_RATIOS = "valuation_ratios"  # FIX-F10: Valuation only
    TECHNICALS_SNAPSHOT = "technicals_snapshot"
    SHARE_STATISTICS = "share_statistics"
    SPLITS_DIVIDENDS = "splits_dividends"
    ANALYST_CONSENSUS = "analyst_consensus"
    EARNINGS_HISTORY = "earnings_history"
    EARNINGS_TREND = "earnings_trend"
    EARNINGS_ANNUAL_TREND = "earnings_annual_trend"
    DIVIDEND_HISTORY = "dividend_history"
    OUTSTANDING_SHARES = "outstanding_shares"
    COMPANY_PROFILE = "company_profile"  # FIX-F4
    INSTITUTIONAL_HOLDERS = "institutional_holders"  # FIX-F6
    FUND_HOLDERS = "fund_holders"  # FIX-F6
    INSIDER_TRANSACTIONS_SNAPSHOT = "insider_transactions_snapshot"  # FIX-F7
