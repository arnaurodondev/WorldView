"""Unit tests for instrument query use cases.

F-A12: GetInstrumentByIdUseCase / GetInstrumentBySymbolUseCase were unused
orphan use cases — they had no API route or worker caller.  They have been
removed from query_instruments.py along with their tests.  The lookup-by-id
and lookup-by-symbol behaviours are covered by InstrumentLookupUseCase tests
(``test_lookup_instrument.py``) and the API route tests
(``test_instruments_lookup.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_instruments import SearchInstrumentsUseCase
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


def _make_uow(items: list[Instrument] | None = None) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.count = AsyncMock(return_value=len(items or []))
    repo.search = AsyncMock(return_value=items or [])
    uow.instruments_read = repo
    return uow


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
