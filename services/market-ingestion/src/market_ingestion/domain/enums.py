"""Domain enumerations for the Market Ingestion service."""

from __future__ import annotations

from enum import StrEnum

from contracts.enums import (
    IngestionTaskStatus as IngestionTaskStatus,  # type: ignore[import-untyped]  # — canonical re-export
)
from messaging.enums import OutboxStatus as OutboxStatus  # — canonical re-export


class Provider(StrEnum):
    EODHD = "eodhd"
    ALPHA_VANTAGE = "alpha_vantage"
    POLYGON = "polygon"
    YAHOO_FINANCE = "yahoo_finance"
    FINNHUB = "finnhub"
    ALPACA = "alpaca"


class DatasetType(StrEnum):
    OHLCV = "ohlcv"  # EOD + intraday (differentiated by timeframe)
    QUOTES = "quotes"  # 15-min delayed real-time quote
    FUNDAMENTALS = "fundamentals"  # Full company fundamentals (all sections)
    EARNINGS_CALENDAR = "earnings_calendar"  # EXT-02
    ECONOMIC_EVENTS = "economic_events"  # EXT-03
    MACRO_INDICATOR = "macro_indicator"  # EXT-04
    NEWS_SENTIMENT = "news_sentiment"  # EXT-05
    INSIDER_TRANSACTIONS = "insider_transactions"  # EXT-06
    YIELD_CURVE = "yield_curve"  # EXT-07
    MARKET_CAP = "market_cap"  # EXT-08


class CacheDatasetType(StrEnum):
    """Cache-layer dataset taxonomy (finer-grained than :class:`DatasetType`).

    This enum lives in the domain layer (R25) so the application layer can
    reference it without importing infrastructure.  It is intentionally
    **distinct** from :class:`DatasetType` (which uses provider-call
    granularity such as ``ohlcv``/``fundamentals``): the cache needs **finer
    grain** (``ohlcv_eod`` vs ``ohlcv_intraday``) because their TTLs differ by
    more than two orders of magnitude.

    Schema-drift mitigation (PLAN-0107 section A.5): the values are part of the
    on-disk Valkey cache key, so they are **append-only** and **never
    renamed**.  The TTL policy table keyed on this enum lives in
    ``infrastructure.cache.cache_policy`` (``CACHE_TTL_SECONDS``).
    """

    OHLCV_EOD = "ohlcv_eod"
    OHLCV_INTRADAY = "ohlcv_intraday"
    FUNDAMENTALS_SNAPSHOT = "fundamentals_snapshot"
    EARNINGS_CALENDAR = "earnings_calendar"
    DIVIDENDS = "dividends"
    SPLITS = "splits"
    EXCHANGES_LIST = "exchanges_list"
    SYMBOL_SEARCH = "symbol_search"


class FundamentalsVariant(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class BackfillStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
