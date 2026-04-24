"""Tests for MarketCalendar — NYSE/NASDAQ trading day and hours logic."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from market_ingestion.domain.market_calendar import MarketCalendar

_CAL = MarketCalendar()


@pytest.mark.unit()
def test_is_trading_day_weekday() -> None:
    # Monday 2026-04-06 is a regular trading day.
    assert _CAL.is_trading_day(date(2026, 4, 6)) is True


@pytest.mark.unit()
def test_is_trading_day_weekend() -> None:
    # Saturday 2026-04-04
    assert _CAL.is_trading_day(date(2026, 4, 4)) is False
    # Sunday 2026-04-05
    assert _CAL.is_trading_day(date(2026, 4, 5)) is False


@pytest.mark.unit()
def test_is_trading_day_holiday() -> None:
    # 2026-01-01 New Year's Day
    assert _CAL.is_trading_day(date(2026, 1, 1)) is False
    # 2026-12-25 Christmas
    assert _CAL.is_trading_day(date(2026, 12, 25)) is False


@pytest.mark.unit()
def test_is_market_open_during_hours() -> None:
    # Monday 2026-04-06 at 14:00 UTC (within 13:30-20:00 window)
    dt = datetime(2026, 4, 6, 14, 0, tzinfo=UTC)
    assert _CAL.is_market_open(dt) is True


@pytest.mark.unit()
def test_is_market_open_outside_hours() -> None:
    # Monday 2026-04-06 at 21:00 UTC (after close at 20:00)
    dt = datetime(2026, 4, 6, 21, 0, tzinfo=UTC)
    assert _CAL.is_market_open(dt) is False

    # Monday 2026-04-06 at 13:00 UTC (before open at 13:30)
    dt_early = datetime(2026, 4, 6, 13, 0, tzinfo=UTC)
    assert _CAL.is_market_open(dt_early) is False


@pytest.mark.unit()
def test_is_market_open_on_weekend() -> None:
    # Saturday 2026-04-04 at 14:00 UTC — market is closed.
    dt = datetime(2026, 4, 4, 14, 0, tzinfo=UTC)
    assert _CAL.is_market_open(dt) is False


@pytest.mark.unit()
def test_is_post_close_in_window() -> None:
    # Monday 2026-04-06 at 20:30 UTC — inside post-close window (20:00-21:00).
    dt = datetime(2026, 4, 6, 20, 30, tzinfo=UTC)
    assert _CAL.is_post_close(dt) is True

    # Monday 2026-04-06 at 21:01 UTC — outside post-close window.
    dt_after = datetime(2026, 4, 6, 21, 1, tzinfo=UTC)
    assert _CAL.is_post_close(dt_after) is False

    # Saturday 2026-04-04 at 20:30 UTC — not a trading day.
    dt_weekend = datetime(2026, 4, 4, 20, 30, tzinfo=UTC)
    assert _CAL.is_post_close(dt_weekend) is False


@pytest.mark.unit()
def test_next_trading_day_skips_weekend() -> None:
    # Friday 2026-04-10 → next trading day should be Monday 2026-04-13
    next_day = _CAL.next_trading_day(date(2026, 4, 10))
    assert next_day == date(2026, 4, 13)


@pytest.mark.unit()
def test_next_trading_day_skips_holiday() -> None:
    # 2026-12-24 (Thursday, not a holiday) → next is 2026-12-28 (skip Fri 12-25 Christmas)
    next_day = _CAL.next_trading_day(date(2026, 12, 24))
    assert next_day == date(2026, 12, 28)
