"""Domain enumerations for the Content Store service."""

from __future__ import annotations

from enum import StrEnum


class DedupOutcome(StrEnum):
    """Result of the 3-stage deduplication pipeline."""

    UNIQUE = "unique"
    CORROBORATING = "corroborating"
    SEMANTIC_NEAR_DUPLICATE = "semantic_near_duplicate"
    SAME_SOURCE_DUPLICATE = "same_source_duplicate"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NORMALIZED = "duplicate_normalized"


class DocumentStatus(StrEnum):
    """Processing status of a canonical document."""

    PROCESSING = "processing"
    STORED = "stored"
    SUPPRESSED = "suppressed"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NEAR = "duplicate_near"


class OutboxStatus(StrEnum):
    """Outbox event lifecycle status."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class ResolutionStatus(StrEnum):
    """Entity mention resolution status."""

    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class SourceType(StrEnum):
    """Content source types matching S4 output."""

    EODHD = "eodhd"
    SEC_EDGAR = "sec_edgar"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    MANUAL = "manual"
