"""Tests for market_ingestion domain enumerations."""

from __future__ import annotations

import pytest
from market_ingestion.domain.enums import (
    BackfillStatus,
    DatasetType,
    FundamentalsVariant,
    IngestionTaskStatus,
    OutboxStatus,
    Provider,
)

# ── Provider ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_provider_values_accessible() -> None:
    assert Provider.EODHD == "eodhd"
    assert Provider.ALPHA_VANTAGE == "alpha_vantage"
    assert Provider.POLYGON == "polygon"
    assert Provider.YAHOO_FINANCE == "yahoo_finance"


@pytest.mark.unit
def test_provider_string_conversion() -> None:
    assert str(Provider.EODHD) == "eodhd"
    assert str(Provider.ALPHA_VANTAGE) == "alpha_vantage"


@pytest.mark.unit
def test_provider_membership_exhaustive() -> None:
    members = {p.value for p in Provider}
    assert members == {"eodhd", "alpha_vantage", "polygon", "yahoo_finance"}


@pytest.mark.unit
def test_provider_from_string() -> None:
    assert Provider("eodhd") is Provider.EODHD
    assert Provider("alpha_vantage") is Provider.ALPHA_VANTAGE


# ── DatasetType ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dataset_type_values_accessible() -> None:
    assert DatasetType.OHLCV == "ohlcv"
    assert DatasetType.QUOTES == "quotes"
    assert DatasetType.FUNDAMENTALS == "fundamentals"


@pytest.mark.unit
def test_dataset_type_membership_exhaustive() -> None:
    members = {d.value for d in DatasetType}
    assert members == {"ohlcv", "quotes", "fundamentals"}


@pytest.mark.unit
def test_dataset_type_iteration() -> None:
    assert len(list(DatasetType)) == 3


# ── FundamentalsVariant ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_fundamentals_variant_values() -> None:
    assert FundamentalsVariant.ANNUAL == "annual"
    assert FundamentalsVariant.QUARTERLY == "quarterly"


@pytest.mark.unit
def test_fundamentals_variant_membership_exhaustive() -> None:
    members = {v.value for v in FundamentalsVariant}
    assert members == {"annual", "quarterly"}


# ── IngestionTaskStatus ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_ingestion_task_status_values() -> None:
    assert IngestionTaskStatus.PENDING == "pending"
    assert IngestionTaskStatus.RUNNING == "running"
    assert IngestionTaskStatus.SUCCEEDED == "succeeded"
    assert IngestionTaskStatus.RETRY == "retry"
    assert IngestionTaskStatus.FAILED == "failed"


@pytest.mark.unit
def test_ingestion_task_status_membership_exhaustive() -> None:
    members = {s.value for s in IngestionTaskStatus}
    assert members == {"pending", "running", "succeeded", "retry", "failed"}


@pytest.mark.unit
def test_ingestion_task_status_from_string() -> None:
    assert IngestionTaskStatus("pending") is IngestionTaskStatus.PENDING
    assert IngestionTaskStatus("failed") is IngestionTaskStatus.FAILED


# ── OutboxStatus ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_outbox_status_values() -> None:
    assert OutboxStatus.PENDING == "pending"
    assert OutboxStatus.PROCESSING == "processing"
    assert OutboxStatus.DELIVERED == "delivered"
    assert OutboxStatus.FAILED == "failed"
    assert OutboxStatus.DEAD_LETTER == "dead_letter"


@pytest.mark.unit
def test_outbox_status_membership_exhaustive() -> None:
    members = {s.value for s in OutboxStatus}
    assert members == {"pending", "processing", "delivered", "failed", "dead_letter"}


# ── BackfillStatus ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_backfill_status_values() -> None:
    assert BackfillStatus.PENDING == "pending"
    assert BackfillStatus.IN_PROGRESS == "in_progress"
    assert BackfillStatus.COMPLETED == "completed"


@pytest.mark.unit
def test_backfill_status_membership_exhaustive() -> None:
    members = {s.value for s in BackfillStatus}
    assert members == {"pending", "in_progress", "completed"}


@pytest.mark.unit
def test_all_enums_are_str_comparable() -> None:
    """Confirm StrEnum semantics: enum members compare equal to their string values."""
    assert Provider.EODHD == "eodhd"
    assert DatasetType.OHLCV == "ohlcv"
    assert FundamentalsVariant.ANNUAL == "annual"
    assert IngestionTaskStatus.PENDING == "pending"
    assert OutboxStatus.DEAD_LETTER == "dead_letter"
    assert BackfillStatus.IN_PROGRESS == "in_progress"
