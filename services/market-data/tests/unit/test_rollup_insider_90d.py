"""Unit tests for the insider 90d rollup worker (PLAN-0089 Wave L-4b).

Covers the pure scheduling helper. The SQL itself (one statement, CTE +
ON CONFLICT) is exercised in the integration ring where a real Postgres
is available.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.rollup_insider_90d import (
    _seconds_until_next_run_hour,
    run_insider_rollup_once,
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


# ── run_insider_rollup_once: emptied-window staleness fix ───────────────────


async def _capture_rollup_sql() -> tuple[str, dict[str, Any]]:
    """Run ``run_insider_rollup_once`` against a mock session and return the SQL.

    Returns (compiled_sql_text, bind_params) of the single statement executed.
    """
    captured: dict[str, Any] = {}

    async def _execute(stmt: Any, params: dict[str, Any] | None = None) -> MagicMock:
        captured["sql"] = str(stmt)
        captured["params"] = params or {}
        result = MagicMock()
        result.rowcount = 95
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    stats = await run_insider_rollup_once(session)
    captured["stats"] = stats
    return captured["sql"], captured["params"]


@pytest.mark.asyncio
async def test_rollup_drives_off_every_instrument_with_raw_data() -> None:
    """The UPSERT must select from a ``have_data`` set (every instrument w/ rows),
    not only from the in-window aggregate — otherwise emptied windows keep a
    stale value (BP-insider-staleness).
    """
    sql, _ = await _capture_rollup_sql()
    lowered = sql.lower()
    assert "have_data" in lowered, f"rollup no longer driven off the full raw-data set:\n{sql}"
    # The INSERT ... SELECT source must be have_data LEFT JOIN agg.
    assert "left join agg" in lowered, f"missing LEFT JOIN to in-window agg:\n{sql}"


@pytest.mark.asyncio
async def test_rollup_coalesces_empty_window_to_zero() -> None:
    """An instrument with raw data but no in-window txns must roll up to 0,
    distinct from NULL ("no insider data ever").
    """
    sql, _ = await _capture_rollup_sql()
    assert "coalesce(agg.total_90d, 0)" in sql.lower(), f"empty window not coalesced to 0:\n{sql}"


@pytest.mark.asyncio
async def test_rollup_window_start_is_90_days_before_today() -> None:
    """The ``:window_start`` bind is exactly today - 90 days (UTC)."""
    import common.time  # type: ignore[import-untyped]

    _, params = await _capture_rollup_sql()
    expected = common.time.utc_now().date() - timedelta(days=90)
    assert params["window_start"] == expected
