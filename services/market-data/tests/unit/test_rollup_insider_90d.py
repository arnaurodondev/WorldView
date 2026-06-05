"""Unit tests for the insider 90d rollup worker (PLAN-0089 Wave L-4b).

Covers the pure scheduling helper. The SQL itself (one statement, CTE +
ON CONFLICT) is exercised in the integration ring where a real Postgres
is available.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_data.application.use_cases.rollup_insider_90d import (
    _seconds_until_next_run_hour,
)

pytestmark = pytest.mark.unit

# ── _seconds_until_next_run_hour ───────────────────────────────────────────


def test_seconds_until_next_run_hour_same_day_before_target() -> None:
    """now = 01:00, target = 03:00 → 2h sleep (7200s)."""
    now = datetime(2026, 5, 28, 1, 0, 0, tzinfo=UTC)
    seconds = _seconds_until_next_run_hour(now=now, target_hour_utc=3)
    assert seconds == pytest.approx(2 * 3600)


def test_seconds_until_next_run_hour_after_target_rolls_to_tomorrow() -> None:
    """now = 04:00, target = 03:00 → 23h sleep until tomorrow 03:00."""
    now = datetime(2026, 5, 28, 4, 0, 0, tzinfo=UTC)
    seconds = _seconds_until_next_run_hour(now=now, target_hour_utc=3)
    assert seconds == pytest.approx(23 * 3600)


def test_seconds_until_next_run_hour_exactly_at_target_rolls_forward() -> None:
    """now exactly == target → roll to tomorrow (otherwise tight infinite loop)."""
    now = datetime(2026, 5, 28, 3, 0, 0, tzinfo=UTC)
    seconds = _seconds_until_next_run_hour(now=now, target_hour_utc=3)
    # Whole 24h.
    assert seconds == pytest.approx(24 * 3600)


def test_seconds_until_next_run_hour_with_minute_offset() -> None:
    """now = 02:30, target = 03:00 → 30 min sleep (1800s)."""
    now = datetime(2026, 5, 28, 2, 30, 0, tzinfo=UTC)
    seconds = _seconds_until_next_run_hour(now=now, target_hour_utc=3)
    assert seconds == pytest.approx(30 * 60)


def test_seconds_until_next_run_hour_midnight_target() -> None:
    """Edge case: target = 00:00, now = 23:00 → 1h sleep."""
    now = datetime(2026, 5, 28, 23, 0, 0, tzinfo=UTC)
    seconds = _seconds_until_next_run_hour(now=now, target_hour_utc=0)
    assert seconds == pytest.approx(3600)


# ── run_insider_rollup_once SQL shape ──────────────────────────────────────


def test_window_constant_is_90_days() -> None:
    """The rollup window must be exactly 90 days (matches the column name)."""
    from market_data.application.use_cases.rollup_insider_90d import _WINDOW_DAYS

    assert _WINDOW_DAYS == 90


def test_min_interval_is_at_least_20_hours() -> None:
    """20h minimum-interval guard prevents duplicate runs after restart."""
    from market_data.application.use_cases.rollup_insider_90d import (
        _MIN_INTERVAL_BETWEEN_RUNS,
    )

    assert _MIN_INTERVAL_BETWEEN_RUNS >= timedelta(hours=20)
