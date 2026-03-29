"""Unit tests for instrument query use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_instruments import (
    GetInstrumentByIdUseCase,
    GetInstrumentBySymbolUseCase,
    SearchInstrumentsUseCase,
)
from market_data.domain.entities import Instrument
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit


def _make_instrument(instrument_id: str = "instr-001", symbol: str = "AAPL") -> Instrument:
    return Instrument(
        id=instrument_id,
        security_id="sec-001",
        symbol=symbol,
        exchange="US",
        flags=InstrumentFlags(has_ohlcv=True, has_quotes=False, has_fundamentals=False),
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _make_uow(instrument: Instrument | None = None, items: list[Instrument] | None = None) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=instrument)
    repo.find_by_symbol_exchange = AsyncMock(return_value=instrument)
    repo.count = AsyncMock(return_value=len(items or []))
    repo.search = AsyncMock(return_value=items or [])
    uow.instruments_read = repo
    return uow


@pytest.mark.asyncio
async def test_get_by_id_found() -> None:
    instrument = _make_instrument()
    uow = _make_uow(instrument=instrument)
    uc = GetInstrumentByIdUseCase(uow)
    result = await uc.execute("instr-001")
    assert result is instrument
    uow.instruments_read.find_by_id.assert_awaited_once_with("instr-001")


@pytest.mark.asyncio
async def test_get_by_id_not_found() -> None:
    uow = _make_uow(instrument=None)
    uc = GetInstrumentByIdUseCase(uow)
    result = await uc.execute("missing")
    assert result is None


@pytest.mark.asyncio
async def test_get_by_symbol_found() -> None:
    instrument = _make_instrument(symbol="TSLA")
    uow = _make_uow(instrument=instrument)
    uc = GetInstrumentBySymbolUseCase(uow)
    result = await uc.execute("TSLA", "US")
    assert result is instrument
    uow.instruments_read.find_by_symbol_exchange.assert_awaited_once_with("TSLA", "US")


@pytest.mark.asyncio
async def test_get_by_symbol_default_exchange() -> None:
    uow = _make_uow(instrument=None)
    uc = GetInstrumentBySymbolUseCase(uow)
    await uc.execute("AAPL")
    uow.instruments_read.find_by_symbol_exchange.assert_awaited_once_with("AAPL", "")


@pytest.mark.asyncio
async def test_search_instruments_returns_total_and_items() -> None:
    items = [_make_instrument("i1", "AAPL"), _make_instrument("i2", "MSFT")]
    uow = _make_uow(items=items)
    uc = SearchInstrumentsUseCase(uow)
    total, result = await uc.execute("A", has_ohlcv=True, limit=10, offset=0)
    assert total == 2
    assert len(result) == 2
    uow.instruments_read.count.assert_awaited_once()
    uow.instruments_read.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_instruments_empty() -> None:
    uow = _make_uow(items=[])
    uc = SearchInstrumentsUseCase(uow)
    total, result = await uc.execute("")
    assert total == 0
    assert result == []
