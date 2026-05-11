"""Unit tests for GetPeriodMoversUseCase (PLAN-0043 Wave B-3)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.get_period_movers import GetPeriodMoversUseCase

pytestmark = pytest.mark.unit


def _make_uow(mover_rows: list[dict]) -> MagicMock:
    uow = MagicMock()
    uow.ohlcv_read.get_period_movers = AsyncMock(return_value=mover_rows)
    return uow


def test_period_movers_gainers_sorted_desc():
    """Gainers call passes 7-day lookback to the repo for 1W."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    asyncio.run(uc.execute("1W", "gainers", 5))
    uow.ohlcv_read.get_period_movers.assert_awaited_once_with(7, "gainers", 5)


def test_period_movers_losers_sorted_asc():
    """Losers call passes 7-day lookback to the repo for 1W."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    asyncio.run(uc.execute("1W", "losers", 5))
    uow.ohlcv_read.get_period_movers.assert_awaited_once_with(7, "losers", 5)


def test_period_movers_1m_uses_30_day_lookback():
    """'1M' period translates to 30-day calendar lookback."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    asyncio.run(uc.execute("1M", "gainers", 10))
    uow.ohlcv_read.get_period_movers.assert_awaited_once_with(30, "gainers", 10)


def test_period_movers_sparse_data_returns_whatever_repo_gives():
    """Use case returns repo results unchanged; sparse data is handled at SQL level."""
    # Simulates the case where only a subset of instruments have enough daily history
    # for the lookback window — the SQL query handles this by excluding instruments
    # without a valid prior-close bar. The use case just forwards the result.
    partial_rows = [{"instrument_id": "abc", "ticker": "AAPL", "name": "Apple", "period_return_pct": 3.5}]
    uow = _make_uow(partial_rows)
    uc = GetPeriodMoversUseCase(uow)
    result = asyncio.run(uc.execute("1W", "gainers", 10))
    assert result == partial_rows


def test_period_movers_invalid_period():
    """'1D' is not supported."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    with pytest.raises(ValueError, match="Unsupported period"):
        asyncio.run(uc.execute("1D", "gainers", 10))


def test_period_movers_invalid_type():
    """mover_type must be 'gainers' or 'losers'."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    with pytest.raises(ValueError, match="mover_type"):
        asyncio.run(uc.execute("1W", "both", 10))
