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
_PROVIDER_PRIORITIES: dict[str, int] = {
    "polygon": 100,
    "yahoo": 80,
    "alpha_vantage": 60,
    "macrotrends": 40,
    "unknown": 0,
}


class Provider(StrEnum):
    """Data provider identifiers, in descending priority order."""

    POLYGON = "polygon"
    YAHOO = "yahoo"
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
