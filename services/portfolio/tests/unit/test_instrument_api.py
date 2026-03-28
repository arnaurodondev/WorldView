"""Unit tests for instrument use cases (get by ID, get by symbol/exchange, list)."""

from __future__ import annotations

import uuid

import pytest
from portfolio.application.use_cases.instrument import (
    GetInstrumentByIdUseCase,
    GetInstrumentUseCase,
    ListInstrumentsUseCase,
)
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.errors import InstrumentNotFoundError

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


def _make_instrument(**kwargs: object) -> InstrumentRef:
    defaults: dict[str, object] = {
        "symbol": "AAPL",
        "exchange": "NASDAQ",
        "source_event_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return InstrumentRef(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


# ── GetInstrumentByIdUseCase ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_instrument_by_id_returns_instrument(uow: FakeUnitOfWork) -> None:
    """GetInstrumentByIdUseCase returns the instrument when it exists."""
    instrument = _make_instrument()
    uow.seed_instrument(instrument)

    result = await GetInstrumentByIdUseCase().execute(instrument.id, uow)

    assert result.id == instrument.id
    assert result.symbol == "AAPL"


@pytest.mark.asyncio
async def test_get_instrument_by_id_raises_when_not_found(uow: FakeUnitOfWork) -> None:
    """GetInstrumentByIdUseCase raises InstrumentNotFoundError for unknown ID."""
    with pytest.raises(InstrumentNotFoundError):
        await GetInstrumentByIdUseCase().execute(uuid.uuid4(), uow)


# ── GetInstrumentUseCase ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_instrument_by_symbol_exchange_returns_instrument(uow: FakeUnitOfWork) -> None:
    """GetInstrumentUseCase returns the instrument for a known symbol/exchange pair."""
    instrument = _make_instrument(symbol="TSLA", exchange="NASDAQ")
    uow.seed_instrument(instrument)

    result = await GetInstrumentUseCase().execute("TSLA", "NASDAQ", uow)

    assert result.symbol == "TSLA"
    assert result.exchange == "NASDAQ"


@pytest.mark.asyncio
async def test_get_instrument_by_symbol_exchange_raises_when_not_found(uow: FakeUnitOfWork) -> None:
    """GetInstrumentUseCase raises InstrumentNotFoundError for unknown symbol/exchange."""
    with pytest.raises(InstrumentNotFoundError):
        await GetInstrumentUseCase().execute("UNKNOWN", "NYSE", uow)


# ── ListInstrumentsUseCase ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_instruments_returns_all(uow: FakeUnitOfWork) -> None:
    """ListInstrumentsUseCase returns all seeded instruments."""
    uow.seed_instrument(_make_instrument(symbol="AAPL", exchange="NASDAQ"))
    uow.seed_instrument(_make_instrument(symbol="MSFT", exchange="NASDAQ"))

    items, total = await ListInstrumentsUseCase().execute(uow)

    assert total == 2
    symbols = {i.symbol for i in items}
    assert symbols == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_list_instruments_empty_repo(uow: FakeUnitOfWork) -> None:
    """ListInstrumentsUseCase returns empty list when repo is empty."""
    items, total = await ListInstrumentsUseCase().execute(uow)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_instruments_respects_limit(uow: FakeUnitOfWork) -> None:
    """ListInstrumentsUseCase respects the limit parameter."""
    for i in range(5):
        uow.seed_instrument(_make_instrument(symbol=f"SYM{i}", exchange="NYSE"))

    items, total = await ListInstrumentsUseCase().execute(uow, limit=2)

    assert len(items) == 2
    assert total == 5
