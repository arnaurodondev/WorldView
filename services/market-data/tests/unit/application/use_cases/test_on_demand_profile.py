"""Unit tests for OnDemandProfileUseCase (PLAN-0073 T-B-1-02).

F-D02: the use case now takes a UoW factory (zero-arg callable returning an
unentered UoW) instead of a single open UoW.  Tests build a tiny async
context-manager wrapper around a MagicMock so the same mock is yielded each
time the use case opens a UoW (Phase 1 read + Phase 3 write share assertions).
"""

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


class _FakeUoWContext:
    """Minimal async-context-manager wrapper exposing a MagicMock as ``uow``.

    The same underlying MagicMock is reused across every ``async with`` block
    so a single test can assert on writes performed in Phase 3 even though
    Phase 1 also opened (and exited) a context.
    """

    def __init__(self, uow_mock: MagicMock) -> None:
        self._uow = uow_mock

    async def __aenter__(self) -> MagicMock:
        return self._uow

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        return None


def _make_uow_mock(
    instrument: Instrument | None = None,
    security: Security | None = None,
) -> MagicMock:
    """Build a single MagicMock that mimics the UoW surface used by the use case."""
    uow = MagicMock()
    uow.instruments_read.find_by_symbol_icase = AsyncMock(return_value=instrument)
    uow.instruments_read.find_by_isin = AsyncMock(return_value=instrument)
    uow.securities_read.find_by_id = AsyncMock(return_value=security)
    uow.securities.update_from_enrichment = AsyncMock()
    uow.instruments.update_metadata = AsyncMock()
    uow.commit = AsyncMock()
    return uow


def _make_factory(uow_mock: MagicMock) -> tuple[MagicMock, callable]:
    """Return ``(uow_mock, factory)`` where ``factory()`` yields a fresh context.

    Phase 1 and Phase 3 each call ``factory()`` once; both contexts hand out
    the same underlying ``uow_mock`` so the test can assert on the cumulative
    set of method calls.
    """

    def factory() -> _FakeUoWContext:
        return _FakeUoWContext(uow_mock)

    return uow_mock, factory


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
    uow_mock, factory = _make_factory(_make_uow_mock(instrument=inst, security=sec))
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(factory, eodhd)

    result = await uc.execute(ticker="AAPL")

    assert result.source == "db"
    assert result.description == "Apple makes iPhones."
    eodhd.get_fundamentals.assert_not_called()
    # F-D02: when DB short-circuits, we never reach Phase 3 — no writes.
    uow_mock.securities.update_from_enrichment.assert_not_called()
    uow_mock.commit.assert_not_called()


async def test_on_demand_db_miss_calls_eodhd_and_persists() -> None:
    """When no instrument by ticker but resolved by ISIN, calls EODHD; persists result."""
    uow_mock = _make_uow_mock()
    # Override: ticker miss, ISIN hit
    uow_mock.instruments_read.find_by_symbol_icase = AsyncMock(return_value=None)
    uow_mock.instruments_read.find_by_isin = AsyncMock(return_value=_make_instrument())
    uow_mock.securities_read.find_by_id = AsyncMock(return_value=_make_security(description=None))
    _, factory = _make_factory(uow_mock)
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(factory, eodhd)

    result = await uc.execute(isin="US0378331005")

    assert result.source == "eodhd_persisted"
    assert result.description == "Apple Inc. designs consumer electronics."
    uow_mock.securities.update_from_enrichment.assert_called_once()
    uow_mock.commit.assert_called_once()


async def test_on_demand_db_hit_null_description_calls_eodhd() -> None:
    """DB row exists but description is None → EODHD is called."""
    inst = _make_instrument()
    sec = _make_security(description=None)
    _uow_mock, factory = _make_factory(_make_uow_mock(instrument=inst, security=sec))
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(factory, eodhd)

    result = await uc.execute(ticker="AAPL")

    assert result.source == "eodhd_persisted"
    eodhd.get_fundamentals.assert_called_once_with("AAPL", "US")


async def test_on_demand_eodhd_404_raises_instrument_not_found() -> None:
    """EODHD returns None (404) → InstrumentNotFoundError raised."""
    inst = _make_instrument()
    _, factory = _make_factory(_make_uow_mock(instrument=inst, security=None))
    eodhd = _make_eodhd_client(response=None)
    uc = OnDemandProfileUseCase(factory, eodhd)

    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(ticker="AAPL")


async def test_on_demand_eodhd_429_propagates_rate_limit_error() -> None:
    """EODHD raises EodhRateLimitError → propagated to caller."""
    inst = _make_instrument()
    _, factory = _make_factory(_make_uow_mock(instrument=inst, security=None))
    eodhd = _make_eodhd_client(raises=EodhRateLimitError("rate limit"))
    uc = OnDemandProfileUseCase(factory, eodhd)

    with pytest.raises(EodhRateLimitError):
        await uc.execute(ticker="AAPL")


async def test_on_demand_invalid_ticker_raises_value_error() -> None:
    """Ticker with path-traversal characters → ValueError (SSRF guard)."""
    _, factory = _make_factory(_make_uow_mock())
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(factory, eodhd)

    # F-S10: error message is now the static "Invalid ticker format" — no echo.
    with pytest.raises(ValueError, match=r"^Invalid ticker format$"):
        await uc.execute(ticker="../../etc/passwd")


async def test_on_demand_invalid_isin_raises_value_error() -> None:
    """ISIN with wrong format → ValueError (SSRF guard)."""
    _, factory = _make_factory(_make_uow_mock())
    eodhd = _make_eodhd_client()
    uc = OnDemandProfileUseCase(factory, eodhd)

    with pytest.raises(ValueError, match=r"^Invalid ISIN format$"):
        await uc.execute(isin="INVALID")


async def test_on_demand_persists_description_to_securities() -> None:
    """After EODHD call, update_from_enrichment is called with description."""
    inst = _make_instrument()
    uow_mock, factory = _make_factory(_make_uow_mock(instrument=inst, security=None))
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(factory, eodhd)

    await uc.execute(ticker="AAPL")

    call_args = uow_mock.securities.update_from_enrichment.call_args
    assert call_args is not None
    security_id, fields = call_args[0]
    assert security_id == _SECURITY_ID
    assert "description" in fields
    assert fields["description"] == "Apple Inc. designs consumer electronics."


async def test_on_demand_persists_metadata_to_instruments() -> None:
    """F-Q10: assert ``instruments.update_metadata`` is called for the EODHD path.

    Previously the mock was created but never asserted on, so a regression in
    Phase 3 (e.g. dropping the instrument metadata write) would have gone
    silently undetected.  This test pins the contract: Phase 3 MUST also
    persist enrichment fields onto the ``instruments`` row.
    """
    inst = _make_instrument(isin=None)  # force ISIN to come from EODHD payload
    uow_mock, factory = _make_factory(_make_uow_mock(instrument=inst, security=None))
    eodhd = _make_eodhd_client(response=_EODHD_RESPONSE)
    uc = OnDemandProfileUseCase(factory, eodhd)

    await uc.execute(ticker="AAPL")

    uow_mock.instruments.update_metadata.assert_called_once()
    call_args = uow_mock.instruments.update_metadata.call_args
    instrument_id, metadata = call_args[0]
    assert instrument_id == _INSTRUMENT_ID
    # ISIN, sector, industry, country, currency_code should be present.
    assert metadata["isin"] == "US0378331005"
    assert metadata["sector"] == "Technology"
    assert metadata["industry"] == "Consumer Electronics"
    assert metadata["country"] == "US"
    assert metadata["currency_code"] == "USD"
