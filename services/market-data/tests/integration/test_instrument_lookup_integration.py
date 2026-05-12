"""Integration tests for /instruments/lookup and /instruments/on-demand-profile.

Uses a real TimescaleDB testcontainer with Alembic-migrated schema.
EODHD HTTP calls are mocked via respx so no real API key is needed.

Run with:
    cd services/market-data
    python -m pytest tests/integration/test_instrument_lookup_integration.py -m integration -v
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response
from market_data.application.use_cases.lookup_instrument import (
    InstrumentLookupUseCase,
)
from market_data.application.use_cases.on_demand_profile import OnDemandProfileUseCase
from market_data.domain.entities import Instrument, Security
from market_data.domain.errors import InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.eodhd.client import EodhHdClient

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# Use a symbol unique to this test file to avoid contamination from
# test_repositories.py which inserts AAPL/XNAS into the shared testcontainer DB.
_ISIN = "US0378331005"
_SYMBOL = "AAPL_LK"
_EXCHANGE = "US"


async def _seed_instrument(uow) -> tuple[Security, Instrument]:
    """Seed a security + instrument row into the test DB."""
    sec = Security(isin=_ISIN, name="Apple Inc.", sector="Technology")
    created_sec = await uow.securities.upsert(sec)
    await uow.commit()

    inst = Instrument(
        security_id=created_sec.id,
        symbol=_SYMBOL,
        exchange=_EXCHANGE,
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        isin=_ISIN,
        sector="Technology",
        industry="Consumer Electronics",
        country="US",
        currency_code="USD",
    )
    created_inst = await uow.instruments.upsert(inst)
    await uow.commit()

    return created_sec, created_inst


async def test_lookup_by_ticker_live_db(uow) -> None:
    """symbol lookup finds seeded instrument in real DB."""
    _sec, inst = await _seed_instrument(uow)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(symbol=_SYMBOL)

    assert result.instrument.symbol == _SYMBOL
    assert result.instrument.exchange == _EXCHANGE
    assert result.instrument.id == inst.id


async def test_lookup_by_isin_live_db(uow) -> None:
    """ISIN lookup resolves instrument from real DB."""
    _sec, inst = await _seed_instrument(uow)
    uc = InstrumentLookupUseCase(uow)

    result = await uc.execute(isin=_ISIN)

    assert result.instrument.isin == _ISIN
    assert result.instrument.id == inst.id


async def test_lookup_not_found_live_db(uow) -> None:
    """Unknown symbol raises InstrumentNotFoundError in real DB (no data seeded)."""
    uc = InstrumentLookupUseCase(uow)

    with pytest.raises(InstrumentNotFoundError):
        await uc.execute(symbol="ZZZZZ_UNKNOWN_9999")


async def test_on_demand_db_hit_live_db(uow) -> None:
    """DB row with description populated returns source='db', no EODHD called."""
    sec = Security(isin=_ISIN, name="Apple Inc.", sector="Technology", description="Apple makes iPhones.")
    created_sec = await uow.securities.upsert(sec)
    await uow.commit()

    inst = Instrument(
        security_id=created_sec.id,
        symbol=_SYMBOL,
        exchange=_EXCHANGE,
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        isin=_ISIN,
    )
    await uow.instruments.upsert(inst)
    await uow.commit()

    eodhd_client = EodhHdClient(api_key="", base_url="https://eodhd.com")
    # F-D02: use case now takes a UoW factory (3-phase R25 pattern).
    uc = OnDemandProfileUseCase(uow.test_uow_factory, eodhd_client)

    result = await uc.execute(ticker=_SYMBOL)

    assert result.source == "db"
    assert result.description == "Apple makes iPhones."


@respx.mock
async def test_on_demand_eodhd_fallback_mocked(uow) -> None:
    """DB row exists but no description → EODHD called (mocked); source='eodhd_persisted'."""
    _sec, inst = await _seed_instrument(uow)

    respx.get("https://eodhd.com/api/fundamentals/AAPL.US").mock(
        return_value=Response(
            200,
            json={
                "General": {
                    "Description": "Apple Inc. designs consumer electronics.",
                    "Sector": "Technology",
                    "Industry": "Consumer Electronics",
                    "CountryISO": "US",
                    "ISIN": _ISIN,
                    "CurrencyCode": "USD",
                }
            },
        )
    )

    eodhd_client = EodhHdClient(api_key="test-key", base_url="https://eodhd.com")
    uc = OnDemandProfileUseCase(uow.test_uow_factory, eodhd_client)

    result = await uc.execute(ticker=_SYMBOL)

    assert result.source == "eodhd_persisted"
    assert result.description == "Apple Inc. designs consumer electronics."
    assert result.sector == "Technology"
    assert result.instrument_id == inst.id


@respx.mock
async def test_on_demand_eodhd_429_propagates_rate_limit_live_db(uow) -> None:
    """F-Q17: EODHD 429 → EodhRateLimitError propagates to caller (no DB write).

    Seeds an instrument with no description so the EODHD path is forced, then
    asserts that the rate-limit error from the mocked respx response surfaces
    out of the use case unchanged — no partial-state commit, no swallowed error.
    """
    from market_data.domain.errors import EodhRateLimitError

    _sec, _inst = await _seed_instrument(uow)

    respx.get("https://eodhd.com/api/fundamentals/AAPL.US").mock(
        return_value=Response(429, text="Rate limit exceeded"),
    )

    eodhd_client = EodhHdClient(api_key="test-key", base_url="https://eodhd.com")
    uc = OnDemandProfileUseCase(uow.test_uow_factory, eodhd_client)

    with pytest.raises(EodhRateLimitError):
        await uc.execute(ticker=_SYMBOL)
