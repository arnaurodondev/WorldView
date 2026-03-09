"""Domain enumerations for the Market Ingestion service."""

from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    EODHD = "eodhd"
    ALPHA_VANTAGE = "alpha_vantage"
    POLYGON = "polygon"
    YAHOO_FINANCE = "yahoo_finance"


class DatasetType(StrEnum):
    OHLCV = "ohlcv"
    QUOTES = "quotes"
    FUNDAMENTALS = "fundamentals"


class FundamentalsVariant(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class IngestionTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class BackfillStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
