"""Unit tests for OnDemandProfileUseCase (PLAN-0073 T-B-1-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.on_demand_profile import OnDemandProfileUseCase
from market_data.domain.entities import Instrument, Security
from market_data.domain.errors import EodhRateLimitError, InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = "018e8e8e-0000-7000-b000-000000000001"
_SECURITY_ID = "018e8e8e-0000-7000-b000-000000000002"


def _make_instrument(isin: str | None = "US0378331005") -> Instrument:
    return Instrument(
        id=_INSTRUMENT_ID,
        security_id=_SECURITY_ID,
        symbol="AAPL",
        exchange="US",
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        isin=isin,
        sector="Technology",
        industry="Consumer Electronics",
        country="US",
        currency_code="USD",
    )


def _make_security(description: str | None = None) -> Security:
    return Security(
        id=_SECURITY_ID,
        isin="US0378331005",
        name="Apple Inc.",
        sector="Technology",
        description=description,
    )


def _make_uow(
    instrument: Instrument | None = None,
    security: Security | None = None,
) -> MagicMock:
    uow = MagicMock()
    uow.instruments_read.find_by_symbol_icase = AsyncMock(return_value=instrument)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=instrument)
    uow.securities_read.find_by_id = AsyncMock(return_value=security)
    uow.securities.update_from_enrichment = AsyncMock()
    uow.instruments.update_metadata = AsyncMock()
    uow.commit = AsyncMock()
    return uow


def _make_eodhd_client(response: dict | None = None, raises: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if raises:
        client.get_fundamentals = AsyncMock(side_effect=raises)
    else:
        client.get_fundamentals = AsyncMock(return_value=response)
    return client


_EODHD_RESPONSE = {
    "General": {
        "Description": "Apple Inc. designs consumer electronics.",
        "Sector": "Technology",
        "Industry": "Consumer Electronics",
        "CountryISO": "US",
        "ISIN": "US0378331005",
        "CurrencyCode": "USD",
    }
}


async def test_on_demand_db_hit_with_description_returns_db() -> None:
    """When DB security already has description, EODHD is NOT called."""
    inst = _make_instrument()
    sec = _make_security(description="Apple makes iPhones.")
    uow = _make_uow(instrument=inst, security=sec)
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(uow, eodhd)

    result = await uc.execute(ticker="AAPL")

    assert result.source == "db"
    assert result.description == "Apple makes iPhones."
    eodhd.get_fundamentals.assert_not_called()


async def test_on_demand_db_miss_calls_eodhd_and_persists() -> None:
    """When no instrument in DB, calls EODHD; persists result."""
    uow = _make_uow(instrument=None)
    uow.instruments_read.find_by_symbol_icase = AsyncMock(return_value=None)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=_make_instrument())
    uow.securities_read.find_by_id = AsyncMock(return_value=_make_security(description=None))
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(uow, eodhd)

    result = await uc.execute(isin="US0378331005")

    assert result.source == "eodhd_persisted"
    assert result.description == "Apple Inc. designs consumer electronics."
    uow.securities.update_from_enrichment.assert_called_once()
    uow.commit.assert_called_once()


async def test_on_demand_db_hit_null_description_calls_eodhd() -> None:
    """DB row exists but description is None → EODHD is called."""
    inst = _make_instrument()
    sec = _make_security(description=None)
    uow = _make_uow(instrument=inst, security=sec)
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(uow, eodhd)

    result = await uc.execute(ticker="AAPL")

    assert result.source == "eodhd_persisted"
    eodhd.get_fundamentals.assert_called_once_with("AAPL", "US")


async def test_on_demand_eodhd_404_raises_instrument_not_found() -> None:
    """EODHD returns None (404) → InstrumentNotFoundError raised."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst, security=None)
    eodhd = _make_eodhd_client(response=None)
    uc = OnDemandProfileUseCase(uow, eodhd)

    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(ticker="AAPL")


async def test_on_demand_eodhd_429_propagates_rate_limit_error() -> None:
    """EODHD raises EodhRateLimitError → propagated to caller."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst, security=None)
    eodhd = _make_eodhd_client(raises=EodhRateLimitError("rate limit"))
    uc = OnDemandProfileUseCase(uow, eodhd)

    with pytest.raises(EodhRateLimitError):
        await uc.execute(ticker="AAPL")


async def test_on_demand_invalid_ticker_raises_value_error() -> None:
    """Ticker with path-traversal characters → ValueError (SSRF guard)."""
    uow = _make_uow()
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(uow, eodhd)

    with pytest.raises(ValueError, match="Invalid ticker"):
        await uc.execute(ticker="../../etc/passwd")


async def test_on_demand_invalid_isin_raises_value_error() -> None:
    """ISIN with wrong format → ValueError (SSRF guard)."""
    uow = _make_uow()
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(uow, eodhd)

    with pytest.raises(ValueError, match="Invalid ISIN"):
        await uc.execute(isin="INVALID")


async def test_on_demand_persists_description_to_securities() -> None:
    """After EODHD call, update_from_enrichment is called with description."""
    inst = _make_instrument()
    uow = _make_uow(instrument=inst, security=None)
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(uow, eodhd)

    await uc.execute(ticker="AAPL")

    call_args = uow.securities.update_from_enrichment.call_args
    assert call_args is not None
    security_id, fields = call_args[0]
    assert security_id == _SECURITY_ID
    assert "description" in fields
    assert fields["description"] == "Apple Inc. designs consumer electronics."
