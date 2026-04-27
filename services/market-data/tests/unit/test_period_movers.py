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
    """Gainers call passes 'gainers' to the repo."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    asyncio.run(uc.execute("1W", "gainers", 5))
    uow.ohlcv_read.get_period_movers.assert_awaited_once_with("1w", "gainers", 5)


def test_period_movers_losers_sorted_asc():
    """Losers call passes 'losers' to the repo."""
    uow = _make_uow([])
    uc = GetPeriodMoversUseCase(uow)
    asyncio.run(uc.execute("1W", "losers", 5))
    uow.ohlcv_read.get_period_movers.assert_awaited_once_with("1w", "losers", 5)


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
