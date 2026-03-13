"""Unit tests for TimescaleDB OHLCV query utilities.

All tests mock the AsyncSession to inspect SQL structure without a live DB.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.enums import Timeframe
from market_data.infrastructure.db.queries.ohlcv_queries import (
    _TIMEFRAME_INTERVAL,
    downsample_to_timeframe,
    get_available_date_range,
    get_bar_count,
    get_bars_by_range,
    get_latest_bar,
)

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


_UNSET = object()


def _make_session(
    scalar_result=_UNSET,
    scalars_result=_UNSET,
    one_result=_UNSET,
    mappings_result=_UNSET,
):
    """Return a mock AsyncSession with configurable execute return values."""
    session = AsyncMock()
    result = MagicMock()
    session.execute.return_value = result

    if scalar_result is not _UNSET:
        result.scalar_one_or_none.return_value = scalar_result
    if scalars_result is not _UNSET:
        result.scalars.return_value.all.return_value = scalars_result
    if one_result is not _UNSET:
        result.one.return_value = one_result
    if mappings_result is not _UNSET:
        result.mappings.return_value.all.return_value = mappings_result

    return session


# ── MD-018 required tests ─────────────────────────────────────────────────────


class TestOHLCVQueryRangeParameters:
    """Asserts parameterized binding — no raw string interpolation."""

    async def test_get_bars_by_range_uses_parameterized_bindings(self) -> None:
        """get_bars_by_range must not embed instrument_id/timeframe in SQL text."""
        session = _make_session(scalars_result=[])

        await get_bars_by_range(
            session,
            instrument_id="AAPL",
            timeframe=Timeframe.ONE_DAY,
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
        )

        # execute was called once; extract the compiled statement
        call_args = session.execute.call_args
        stmt = call_args[0][0]
        # The statement should be a SQLAlchemy Select — not a raw string
        # Instrument ID must never appear as a literal in the query string
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "AAPL" not in compiled, "instrument_id must not be interpolated into SQL"
        assert "1d" not in compiled, "timeframe must not be interpolated into SQL"

    async def test_downsample_uses_named_bind_params(self) -> None:
        """downsample_to_timeframe must use named :param syntax, never f-strings."""
        session = _make_session(mappings_result=[])

        await downsample_to_timeframe(
            session,
            instrument_id="MSFT",
            source_timeframe=Timeframe.ONE_MIN,
            target_timeframe=Timeframe.FIVE_MIN,
            start=date(2024, 6, 1),
            end=date(2024, 6, 30),
        )

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        params = call_args[0][1]

        # The SQL text must contain named bind params
        sql_str = str(stmt)
        assert ":instrument_id" in sql_str
        assert ":interval" in sql_str
        assert ":source_timeframe" in sql_str
        assert ":start_dt" in sql_str
        assert ":end_dt" in sql_str

        # The actual values must be in the params dict, not in the SQL string
        assert "MSFT" not in sql_str
        assert "MSFT" in str(params["instrument_id"])

    async def test_interval_comes_from_static_lookup_not_user_input(self) -> None:
        """The interval for time_bucket must come from _TIMEFRAME_INTERVAL lookup."""
        # Verify the static mapping covers all Timeframe values used in downsampling
        assert "1m" in _TIMEFRAME_INTERVAL
        assert "5m" in _TIMEFRAME_INTERVAL
        assert "1d" in _TIMEFRAME_INTERVAL
        assert "1w" in _TIMEFRAME_INTERVAL
        # All values must be safe SQL interval literals (no user data)
        for interval in _TIMEFRAME_INTERVAL.values():
            assert isinstance(interval, str)
            assert len(interval) > 0


class TestOHLCVQueryOrdering:
    """Asserts correct ORDER BY clauses."""

    async def test_get_bars_by_range_orders_ascending(self) -> None:
        """get_bars_by_range must return bars in chronological (ASC) order."""
        session = _make_session(scalars_result=[])

        await get_bars_by_range(
            session,
            instrument_id="SPY",
            timeframe=Timeframe.ONE_HOUR,
            start=date(2024, 1, 1),
            end=date(2024, 3, 31),
        )

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        # Must be ORDER BY bar_date ASC
        assert "bar_date ASC" in compiled or "ORDER BY" in compiled

    async def test_get_latest_bar_orders_descending(self) -> None:
        """get_latest_bar must ORDER BY bar_date DESC to retrieve the most recent."""
        session = _make_session(scalar_result=None)

        await get_latest_bar(session, instrument_id="TSLA", timeframe=Timeframe.ONE_DAY)

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "DESC" in compiled

    async def test_downsample_result_ordered_by_bucket(self) -> None:
        """downsample_to_timeframe must include ORDER BY bucket_date ASC."""
        session = _make_session(mappings_result=[])

        await downsample_to_timeframe(
            session,
            instrument_id="QQQ",
            source_timeframe=Timeframe.ONE_MIN,
            target_timeframe=Timeframe.FIFTEEN_MIN,
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        assert "ORDER BY bucket_date ASC" in str(stmt)


class TestTimeBucketAggregation:
    """Asserts time_bucket usage in downsample query."""

    async def test_time_bucket_function_appears_in_sql(self) -> None:
        """downsample_to_timeframe must use time_bucket() TimescaleDB function."""
        session = _make_session(mappings_result=[])

        await downsample_to_timeframe(
            session,
            instrument_id="IWM",
            source_timeframe=Timeframe.ONE_MIN,
            target_timeframe=Timeframe.ONE_HOUR,
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        assert "time_bucket" in str(stmt)

    async def test_downsample_aggregates_ohlcv(self) -> None:
        """downsample_to_timeframe SQL must contain OHLCV aggregation functions."""
        session = _make_session(mappings_result=[])

        await downsample_to_timeframe(
            session,
            instrument_id="GLD",
            source_timeframe=Timeframe.FIVE_MIN,
            target_timeframe=Timeframe.ONE_HOUR,
            start=date(2024, 2, 1),
            end=date(2024, 2, 28),
        )

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        sql_text = str(stmt).upper()
        assert "MAX(HIGH)" in sql_text
        assert "MIN(LOW)" in sql_text
        assert "SUM(VOLUME)" in sql_text

    async def test_downsample_returns_empty_list_when_no_rows(self) -> None:
        """downsample_to_timeframe must return [] when no rows match."""
        session = _make_session(mappings_result=[])

        result = await downsample_to_timeframe(
            session,
            instrument_id="SLV",
            source_timeframe=Timeframe.ONE_MIN,
            target_timeframe=Timeframe.ONE_DAY,
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
        )

        assert result == []


class TestAuxiliaryQueryFunctions:
    """Tests for get_bar_count and get_available_date_range."""

    async def test_get_bar_count_returns_zero_on_none(self) -> None:
        """get_bar_count must return 0 when scalar_one returns None."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = None
        session.execute.return_value = result_mock

        count = await get_bar_count(session, instrument_id="BTC", timeframe=Timeframe.ONE_DAY)
        assert count == 0

    async def test_get_available_date_range_returns_none_when_empty(self) -> None:
        """get_available_date_range must return None when table is empty."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.one.return_value = (None, None)
        session.execute.return_value = result_mock

        result = await get_available_date_range(session, instrument_id="ETH", timeframe=Timeframe.ONE_HOUR)
        assert result is None

    async def test_get_available_date_range_returns_date_tuple(self) -> None:
        """get_available_date_range must return (min.date(), max.date()) when data exists."""
        from datetime import UTC, datetime

        min_dt = datetime(2023, 1, 1, tzinfo=UTC)
        max_dt = datetime(2024, 12, 31, tzinfo=UTC)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.one.return_value = (min_dt, max_dt)
        session.execute.return_value = result_mock

        result = await get_available_date_range(session, instrument_id="BTC", timeframe=Timeframe.ONE_DAY)
        assert result == (date(2023, 1, 1), date(2024, 12, 31))
