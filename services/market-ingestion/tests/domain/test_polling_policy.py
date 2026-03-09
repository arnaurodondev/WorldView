"""Tests for PollingPolicy entity — adaptive scheduling and priority ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_ingestion.domain.entities.polling_policy import PollingPolicy

UTC = UTC


@pytest.mark.unit
def test_policy_default_values() -> None:
    policy = PollingPolicy()
    assert policy.id is not None
    assert policy.base_interval_seconds == 3600.0
    assert policy.hotness == 0.0
    assert policy.k == 1.0
    assert policy.priority == 0
    assert policy.is_enabled is True
    assert policy.symbol is None


@pytest.mark.unit
def test_adaptive_interval_no_hotness() -> None:
    policy = PollingPolicy(base_interval_seconds=3600.0, k=1.0, hotness=0.0)
    assert policy.effective_interval_seconds == 3600.0


@pytest.mark.unit
def test_adaptive_interval_full_hotness() -> None:
    policy = PollingPolicy(base_interval_seconds=3600.0, k=1.0, hotness=1.0)
    # 3600 / (1 + 1*1) = 1800
    assert policy.effective_interval_seconds == 1800.0


@pytest.mark.unit
def test_adaptive_interval_partial_hotness() -> None:
    policy = PollingPolicy(base_interval_seconds=1000.0, k=2.0, hotness=0.5)
    # 1000 / (1 + 2*0.5) = 1000/2 = 500
    assert policy.effective_interval_seconds == 500.0


@pytest.mark.unit
def test_priority_ordering_higher_priority_is_less() -> None:
    low = PollingPolicy(priority=1)
    high = PollingPolicy(priority=10)
    assert high < low  # higher priority value → "less than" in a min-heap


@pytest.mark.unit
def test_priority_ordering_sorted() -> None:
    policies = [PollingPolicy(priority=1), PollingPolicy(priority=5), PollingPolicy(priority=3)]
    ordered = sorted(policies)
    assert ordered[0].priority == 5
    assert ordered[1].priority == 3
    assert ordered[2].priority == 1


@pytest.mark.unit
def test_wildcard_symbol_matches_any() -> None:
    policy = PollingPolicy(symbol=None)
    assert policy.matches("AAPL") is True
    assert policy.matches("TSLA") is True
    assert policy.matches("BTC-USD") is True


@pytest.mark.unit
def test_specific_symbol_matches_only_itself() -> None:
    policy = PollingPolicy(symbol="AAPL")
    assert policy.matches("AAPL") is True
    assert policy.matches("TSLA") is False


@pytest.mark.unit
def test_is_due_when_never_run() -> None:
    policy = PollingPolicy(base_interval_seconds=3600.0)
    assert policy.is_due(None) is True


@pytest.mark.unit
def test_is_due_when_interval_elapsed() -> None:
    policy = PollingPolicy(base_interval_seconds=60.0)
    last_run = datetime.now(UTC) - timedelta(seconds=61)
    assert policy.is_due(last_run) is True


@pytest.mark.unit
def test_not_due_when_interval_not_elapsed() -> None:
    policy = PollingPolicy(base_interval_seconds=3600.0)
    last_run = datetime.now(UTC) - timedelta(seconds=10)
    assert policy.is_due(last_run) is False


@pytest.mark.unit
def test_backfill_fields_stored() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    policy = PollingPolicy(backfill_days=365, backfill_start_date=start)
    assert policy.backfill_days == 365
    assert policy.backfill_start_date == start


@pytest.mark.unit
def test_policy_id_is_ulid_string() -> None:
    policy = PollingPolicy()
    assert isinstance(policy.id, str)
    assert len(policy.id) == 26
