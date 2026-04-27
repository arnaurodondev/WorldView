"""Unit tests for GetSectorReturnsUseCase (PLAN-0043 Wave B-3)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.get_sector_returns import GetSectorReturnsUseCase

pytestmark = pytest.mark.unit


def _make_uow(sector_rows: list[dict]) -> MagicMock:
    uow = MagicMock()
    uow.ohlcv_read.get_sector_period_returns = AsyncMock(return_value=sector_rows)
    return uow


def test_sector_returns_maps_1w_to_timeframe():
    """'1W' period must translate to '1w' timeframe for OHLCV query."""
    uow = _make_uow([])
    uc = GetSectorReturnsUseCase(uow)
    asyncio.run(uc.execute("1W"))
    uow.ohlcv_read.get_sector_period_returns.assert_awaited_once_with("1w")


def test_sector_returns_maps_1m_to_timeframe():
    """'1M' period must translate to '1M' timeframe."""
    uow = _make_uow([])
    uc = GetSectorReturnsUseCase(uow)
    asyncio.run(uc.execute("1M"))
    uow.ohlcv_read.get_sector_period_returns.assert_awaited_once_with("1M")


def test_sector_returns_invalid_period():
    """'1D' is not supported — S9 handles 1D via the screener path."""
    uow = _make_uow([])
    uc = GetSectorReturnsUseCase(uow)
    with pytest.raises(ValueError, match="Unsupported period"):
        asyncio.run(uc.execute("1D"))


def test_sector_returns_passes_through_rows():
    """Use case returns whatever the repo produces unchanged."""
    rows = [{"name": "Technology", "change_pct": 2.5, "instrument_count": 5}]
    uow = _make_uow(rows)
    uc = GetSectorReturnsUseCase(uow)
    result = asyncio.run(uc.execute("1W"))
    assert result == rows
