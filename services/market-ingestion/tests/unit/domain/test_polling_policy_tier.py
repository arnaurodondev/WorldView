"""Tests for PollingPolicy tier-aware scheduling (W2-2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from market_ingestion.domain.entities.polling_policy import PollingPolicy

pytestmark = pytest.mark.unit


@pytest.mark.unit()
def test_post_market_only_policy_skips_during_market_hours() -> None:
    """A post_market_only policy must not be due during NYSE market hours."""
    policy = PollingPolicy(base_interval_seconds=60.0, post_market_only=True)
    # Simulate being inside market hours (13:30-20:00 UTC on a weekday)
    # Patch _is_market_hours_now to return True so we don't depend on wall clock.
    with patch(
        "market_ingestion.domain.entities.polling_policy._is_market_hours_now",
        return_value=True,
    ):
        # Even though last_run_at is None (would normally be due), market hours block it.
        assert policy.is_due(None) is False


@pytest.mark.unit()
def test_post_market_only_policy_runs_outside_market_hours() -> None:
    """A post_market_only policy is eligible outside NYSE market hours."""
    policy = PollingPolicy(base_interval_seconds=60.0, post_market_only=True)
    # Patch _is_market_hours_now to return False (off-hours / weekend / holiday).
    with patch(
        "market_ingestion.domain.entities.polling_policy._is_market_hours_now",
        return_value=False,
    ):
        # Never run before → is_due returns True.
        assert policy.is_due(None) is True

        # Run 2 minutes ago → interval elapsed (60s) → is_due returns True.
        last_run = datetime(2026, 4, 6, 20, 30, tzinfo=UTC)
        with patch(
            "market_ingestion.domain.entities.polling_policy.utc_now",
            return_value=datetime(2026, 4, 6, 20, 32, tzinfo=UTC),
        ):
            assert policy.is_due(last_run) is True


@pytest.mark.unit()
def test_post_market_only_false_unaffected_by_market_hours() -> None:
    """A policy with post_market_only=False follows normal is_due logic regardless of market hours."""
    policy = PollingPolicy(base_interval_seconds=60.0, post_market_only=False)
    with patch(
        "market_ingestion.domain.entities.polling_policy._is_market_hours_now",
        return_value=True,
    ):
        assert policy.is_due(None) is True
