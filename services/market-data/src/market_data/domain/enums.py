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
# Priority ladder (higher wins): derived Alpaca-1m aggregates are the authoritative
# source for every timeframe they cover and are written via the unconditional
# ``bulk_upsert_derived`` path, but we still rank ``alpaca``/``derived`` at the top
# so that any priority-guarded comparison agrees with that intent.  Yahoo (deep
# daily) outranks EODHD so EODHD only wins when it is genuinely the sole source.
_PROVIDER_PRIORITIES: dict[str, int] = {
    "alpaca": 110,  # 1m bars + their derived higher timeframes — single source of truth
    "derived": 110,  # locally-derived (from Alpaca 1m) — authoritative for covered window
    "polygon": 100,  # alternate intraday provider (registered only when keyed)
    "yahoo_finance": 80,  # deep daily history (free/keyless) — preferred over EODHD
    "yahoo": 80,  # legacy alias — kept so historical rows compare consistently
    "eodhd": 60,  # last-resort daily failover only
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
