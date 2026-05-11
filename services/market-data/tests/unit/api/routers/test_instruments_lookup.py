"""Unit tests for /instruments/lookup and /instruments/on-demand-profile (PLAN-0073 T-B-1-03)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_lookup_instrument_uc,
    get_on_demand_profile_uc,
    require_internal_jwt,
)
from market_data.api.routers import instruments
from market_data.application.use_cases.lookup_instrument import InstrumentLookupResult
from market_data.application.use_cases.on_demand_profile import OnDemandProfileData
from market_data.domain.entities import Instrument, Security
from market_data.domain.errors import EodhRateLimitError, InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = "018e8e8e-0000-7000-b000-000000000001"
_SECURITY_ID = "018e8e8e-0000-7000-b000-000000000002"


def _make_instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(
        id=_INSTRUMENT_ID,
        security_id=_SECURITY_ID,
        symbol=symbol,
        exchange="US",
        flags=InstrumentFlags(has_ohlcv=True),
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        isin="US0378331005",
        sector="Technology",
        industry="Consumer Electronics",
        country="US",
        currency_code="USD",
    )


def _make_security() -> Security:
    return Security(
        id=_SECURITY_ID,
        isin="US0378331005",
        name="Apple Inc.",
        sector="Technology",
        description="Apple Inc. designs consumer electronics.",
    )


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_app(
    mock_lookup_uc: MagicMock | None = None,
    mock_on_demand_uc: MagicMock | None = None,
    bypass_jwt: bool = True,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(instruments.router, prefix="/api/v1")

    if mock_lookup_uc is not None:
        app.dependency_overrides[get_lookup_instrument_uc] = lambda: mock_lookup_uc
    if mock_on_demand_uc is not None:
        app.dependency_overrides[get_on_demand_profile_uc] = lambda: mock_on_demand_uc
    if bypass_jwt:
        app.dependency_overrides[require_internal_jwt] = lambda: None

    return app, TestClient(app)


def _make_lookup_uc_found(instrument: Instrument, security: Security | None = None) -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=InstrumentLookupResult(instrument=instrument, security=security))
    return uc


def _make_lookup_uc_not_found() -> MagicMock:
    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=InstrumentNotFoundError("not found"))
    return uc


def _make_on_demand_uc(data: OnDemandProfileData | None = None, raises: Exception | None = None) -> MagicMock:
    uc = MagicMock()
    if raises:
        uc.execute = AsyncMock(side_effect=raises)
    else:
        uc.execute = AsyncMock(return_value=data)
    return uc


_PROFILE_DATA = OnDemandProfileData(
    instrument_id=_INSTRUMENT_ID,
    security_id=_SECURITY_ID,
    ticker="AAPL",
    exchange="US",
    isin="US0378331005",
    currency_code="USD",
    description="Apple Inc. designs consumer electronics.",
    sector="Technology",
    industry="Consumer Electronics",
    country="US",
    source="eodhd_persisted",
)


def test_lookup_200_base() -> None:
    """GET /instruments/lookup?symbol=AAPL returns 200 with base fields."""
    inst = _make_instrument()
    _, client = _make_app(mock_lookup_uc=_make_lookup_uc_found(inst))
    resp = client.get("/api/v1/instruments/lookup?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["id"] == _INSTRUMENT_ID
    # Base response has is_active but NOT description (extra_info=False)
    assert "is_active" in data
    assert "description" not in data


def test_lookup_200_extra_info() -> None:
    """GET /instruments/lookup?symbol=AAPL&extra_info=true returns enrichment fields."""
    inst = _make_instrument()
    sec = _make_security()
    _, client = _make_app(mock_lookup_uc=_make_lookup_uc_found(inst, security=sec))
    resp = client.get("/api/v1/instruments/lookup?symbol=AAPL&extra_info=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["description"] == "Apple Inc. designs consumer electronics."
    assert data["sector"] == "Technology"


def test_lookup_404() -> None:
    """Unknown symbol returns 404."""
    _, client = _make_app(mock_lookup_uc=_make_lookup_uc_not_found())
    resp = client.get("/api/v1/instruments/lookup?symbol=UNKNOWN")
    assert resp.status_code == 404


def test_lookup_400_no_params() -> None:
    """No query params returns 400 (ValueError from use case)."""
    uc = MagicMock()
    uc.execute = AsyncMock(side_effect=ValueError("At least one param required"))
    _, client = _make_app(mock_lookup_uc=uc)
    resp = client.get("/api/v1/instruments/lookup")
    assert resp.status_code == 400


def test_on_demand_200() -> None:
    """GET /instruments/on-demand-profile?ticker=AAPL returns 200."""
    _, client = _make_app(mock_on_demand_uc=_make_on_demand_uc(data=_PROFILE_DATA))
    resp = client.get("/api/v1/instruments/on-demand-profile?ticker=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["description"] == "Apple Inc. designs consumer electronics."
    assert data["source"] == "eodhd_persisted"


def test_on_demand_404() -> None:
    """Not found → 404."""
    _, client = _make_app(mock_on_demand_uc=_make_on_demand_uc(raises=InstrumentNotFoundError("not found")))
    resp = client.get("/api/v1/instruments/on-demand-profile?ticker=ZZZZZ")
    assert resp.status_code == 404


def test_on_demand_429() -> None:
    """EODHD rate limit → 429."""
    _, client = _make_app(mock_on_demand_uc=_make_on_demand_uc(raises=EodhRateLimitError("rate limit")))
    resp = client.get("/api/v1/instruments/on-demand-profile?ticker=AAPL")
    assert resp.status_code == 429


def test_on_demand_requires_internal_jwt() -> None:
    """Without X-Internal-JWT header, /on-demand-profile returns 401."""
    _, client = _make_app(bypass_jwt=False)
    resp = client.get("/api/v1/instruments/on-demand-profile?ticker=AAPL")
    assert resp.status_code == 401


def test_old_symbol_endpoint_removed() -> None:
    """GET /instruments/symbol/AAPL returns 404 (route no longer exists)."""
    _, client = _make_app()
    resp = client.get("/api/v1/instruments/symbol/AAPL")
    assert resp.status_code == 404
