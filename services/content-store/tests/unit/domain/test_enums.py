"""Unit tests for domain enumerations."""

from __future__ import annotations

import pytest
from content_store.domain.enums import (
    DedupOutcome,
    DocumentStatus,
    OutboxStatus,
    ResolutionStatus,
    SourceType,
)

pytestmark = pytest.mark.unit


class TestDedupOutcome:
    def test_all_values_present(self) -> None:
        expected = {
            "unique",
            "corroborating",
            "semantic_near_duplicate",
            "same_source_duplicate",
            "duplicate_exact",
            "duplicate_normalized",
        }
        assert {v.value for v in DedupOutcome} == expected

    def test_string_comparison(self) -> None:
        assert DedupOutcome.UNIQUE == "unique"
        assert DedupOutcome.CORROBORATING == "corroborating"


class TestDocumentStatus:
    def test_all_values_present(self) -> None:
        expected = {"processing", "stored", "suppressed", "duplicate_exact", "duplicate_near"}
        assert {v.value for v in DocumentStatus} == expected


class TestSourceType:
    def test_all_five_sources(self) -> None:
        expected = {"eodhd", "sec_edgar", "finnhub", "newsapi", "manual"}
        assert {v.value for v in SourceType} == expected


class TestOutboxStatus:
    def test_values(self) -> None:
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.DELIVERED == "delivered"


class TestResolutionStatus:
    def test_values(self) -> None:
        assert ResolutionStatus.UNRESOLVED == "UNRESOLVED"
        assert ResolutionStatus.RESOLVED == "RESOLVED"
        assert ResolutionStatus.FAILED == "FAILED"
