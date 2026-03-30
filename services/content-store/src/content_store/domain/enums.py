"""Domain enumerations for the Content Store service."""

from __future__ import annotations

from enum import StrEnum

from contracts.enums import ContentSourceType as SourceType
from messaging.enums import OutboxStatus as OutboxStatus

__all__ = [  # — intentional grouping: re-exports first, then local
    "DedupOutcome",
    "DocumentStatus",
    "OutboxStatus",
    "ResolutionStatus",
    "SourceType",
]


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


class ResolutionStatus(StrEnum):
    """Entity mention resolution status."""

    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
