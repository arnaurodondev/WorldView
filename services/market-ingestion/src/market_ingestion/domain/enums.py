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


class FundamentalsVariant(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class BackfillStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
