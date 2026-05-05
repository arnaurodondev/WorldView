"""Unit tests for InstrumentLookupUseCase (PLAN-0073 T-B-1-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.lookup_instrument import (
    InstrumentLookupResult,
    InstrumentLookupUseCase,
)
from market_data.domain.entities import Instrument, Security
from market_data.domain.errors import InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = "018e8e8e-0000-7000-b000-000000000001"
_SECURITY_ID = "018e8e8e-0000-7000-b000-000000000002"
_ISIN = "US0378331005"


def _make_instrument(
    symbol: str = "AAPL",
    isin: str | None = _ISIN,
    sector: str | None = "Technology",
    description: str | None = None,
) -> Instrument:
    return Instrument(
        id=_INSTRUMENT_ID,
        security_id=_SECURITY_ID,
        symbol=symbol,
        exchange="US",
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        isin=isin,
        sector=sector,
        industry="Consumer Electronics",
        country="US",
        currency_code="USD",
    )


def _make_security(description: str | None = None) -> Security:
    return Security(
        id=_SECURITY_ID,
        isin=_ISIN,
        name="Apple Inc.",
        sector="Technology",
        description=description,
    )


def _make_uow(
    instrument: Instrument | None = None,
    security: Security | None = None,
) -> MagicMock:
    uow = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=instrument)
    uow.instruments_read.find_by_symbol_icase = AsyncMock(return_value=instrument)
    uow.securities_read.find_by_id = AsyncMock(return_value=security)
    return uow


async def test_lookup_by_id_returns_base() -> None:
    """id lookup returns InstrumentLookupResult with instrument and no security."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(id=_INSTRUMENT_ID)

    assert isinstance(result, InstrumentLookupResult)
    assert result.instrument.id == _INSTRUMENT_ID
    assert result.security is None
    uow.instruments_read.find_by_id.assert_called_once_with(_INSTRUMENT_ID)


async def test_lookup_by_isin_returns_base() -> None:
    """isin lookup resolves when id is None."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst)
    uow.instruments_read.find_by_id = AsyncMock(return_value=None)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(isin=_ISIN)

    assert result.instrument.symbol == "AAPL"
    uow.instruments_read.find_by_isin.assert_called_once_with(_ISIN)


async def test_lookup_by_symbol_case_insensitive() -> None:
    """Symbol lookup is forwarded as-is to find_by_symbol_icase (ilike in repo)."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst)
    uow.instruments_read.find_by_id = AsyncMock(return_value=None)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=None)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(symbol="aapl")

    assert result.instrument.symbol == "AAPL"
    uow.instruments_read.find_by_symbol_icase.assert_called_once_with("aapl")


async def test_lookup_priority_id_over_isin() -> None:
    """When both id and isin are provided, id wins (find_by_id is tried first)."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(id=_INSTRUMENT_ID, isin=_ISIN)

    assert result.instrument.id == _INSTRUMENT_ID
    uow.instruments_read.find_by_id.assert_called_once()
    uow.instruments_read.find_by_isin.assert_not_called()


async def test_lookup_extra_info_fetches_security() -> None:
    """extra_info=True also fetches the linked Security."""
    inst = _make_instrument()
    sec = _make_security(description="Apple makes iPhones.")
    uow = _make_uow(instrument=inst, security=sec)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(id=_INSTRUMENT_ID, extra_info=True)

    assert result.security is not None
    assert result.security.description == "Apple makes iPhones."
    uow.securities_read.find_by_id.assert_called_once_with(_SECURITY_ID)


async def test_lookup_extra_info_description_null_when_missing() -> None:
    """extra_info=True with no description → security.description is None."""
    inst = _make_instrument()
    sec = _make_security(description=None)
    uow = _make_uow(instrument=inst, security=sec)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(id=_INSTRUMENT_ID, extra_info=True)

    assert result.security is not None
    assert result.security.description is None


async def test_lookup_no_params_raises_value_error() -> None:
    """All-None params raises ValueError."""
    uow = _make_uow()
    uc = InstrumentLookupUseCase(uow)

    with pytest.raises(ValueError, match="At least one"):
        await uc.execute()


async def test_lookup_not_found_raises_instrument_not_found_error() -> None:
    """No DB row raises InstrumentNotFoundError."""
    uow = _make_uow(instrument=None)
    uow.instruments_read.find_by_id = AsyncMock(return_value=None)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=None)
    uow.instruments_read.find_by_symbol_icase = AsyncMock(return_value=None)
    uc = InstrumentLookupUseCase(uow)

    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(symbol="UNKNOWN")
