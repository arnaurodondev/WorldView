"""Unit tests for GET /api/v1/fundamentals/history (PLAN-0066 Wave G, T-W10-G-02).

Tests cover 3-identifier resolution, 404 on unknown instrument, period count
limiting, and null fields in the response.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_fundamentals_history_uc,
    get_lookup_instrument_uc,
)
from market_data.api.routers import fundamentals as fundamentals_router
from market_data.domain.entities import Instrument
from market_data.domain.errors import InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit

_INSTRUMENT_UUID = str(uuid4())
_TICKER = "MSFT"
_ISIN = "US5949181045"


# ── Helpers ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    yield


def _make_instrument(symbol: str = _TICKER, iid: str = _INSTRUMENT_UUID) -> Instrument:
    return Instrument(
        id=iid,
        security_id=str(uuid4()),
        symbol=symbol,
        exchange="NASDAQ",
        flags=InstrumentFlags(),
    )


def _make_lookup_uc(instrument: Instrument | None = None, *, raise_not_found: bool = False) -> MagicMock:
    from market_data.application.use_cases.lookup_instrument import InstrumentLookupResult

    uc = MagicMock()
    if raise_not_found:
        uc.execute = AsyncMock(side_effect=InstrumentNotFoundError("not found"))
    else:
        instr = instrument or _make_instrument()
        uc.execute = AsyncMock(return_value=InstrumentLookupResult(instrument=instr))
    return uc


def _make_history_uc(num_periods: int = 4) -> MagicMock:
    """Mock GetFundamentalsHistoryUseCase returning synthetic periods."""
    periods = [
        {
            "period": f"Q{i % 4 + 1} 2024",
            "period_end_date": f"2024-0{i + 1}-31" if i < 9 else f"2024-{i + 1}-31",
            "revenue": 500_000_000.0 * (i + 1),
            "gross_profit": 200_000_000.0 * (i + 1),
            "net_income": 100_000_000.0 * (i + 1),
            "eps": 1.5 + i * 0.1,
            "pe_ratio": 30.0,
            "market_cap": 2_000_000_000_000.0,
        }
        for i in range(num_periods)
    ]
    uc = MagicMock()
    uc.execute = AsyncMock(return_value={"periods": periods, "period_count": num_periods})
    return uc


def _make_history_uc_null_fields(num_periods: int = 2) -> MagicMock:
    """Mock returning periods with null financial fields."""
    periods = [
        {
            "period": "Q1 2024",
            "period_end_date": "2024-03-31",
            "revenue": None,
            "gross_profit": None,
            "net_income": None,
            "eps": 1.5,
            "pe_ratio": None,
            "market_cap": None,
        }
    ] * num_periods
    uc = MagicMock()
    uc.execute = AsyncMock(return_value={"periods": periods, "period_count": num_periods})
    return uc


def _make_app(
    lookup_uc: MagicMock | None = None,
    history_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(fundamentals_router.router, prefix="/api/v1")

    if lookup_uc is not None:
        app.dependency_overrides[get_lookup_instrument_uc] = lambda: lookup_uc
    if history_uc is not None:
        app.dependency_overrides[get_fundamentals_history_uc] = lambda: history_uc

    return app, TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_fundamentals_history_resolves_by_symbol() -> None:
    """GET /fundamentals/history?symbol=MSFT → lookup called with symbol."""
    lookup_uc = _make_lookup_uc()
    history_uc = _make_history_uc(4)
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history?symbol=MSFT")

    assert resp.status_code == 200
    lookup_uc.execute.assert_awaited_once()
    _, call_kwargs = lookup_uc.execute.call_args
    assert call_kwargs.get("symbol") == "MSFT"
    assert call_kwargs.get("id") is None


def test_fundamentals_history_returns_400_if_no_identifier() -> None:
    """GET /fundamentals/history with no identifier → HTTP 400."""
    lookup_uc = _make_lookup_uc()
    history_uc = _make_history_uc()
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history")

    assert resp.status_code == 400
    assert "required" in resp.json()["detail"].lower() or "instrument_id" in resp.json()["detail"].lower()


def test_fundamentals_history_returns_404_if_not_found() -> None:
    """GET /fundamentals/history with unknown symbol → HTTP 404."""
    lookup_uc = _make_lookup_uc(raise_not_found=True)
    history_uc = _make_history_uc()
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history?symbol=UNKNOWN")

    assert resp.status_code == 404


def test_fundamentals_history_returns_n_periods() -> None:
    """GET /fundamentals/history?periods=4 → at most 4 periods in response."""
    lookup_uc = _make_lookup_uc()
    history_uc = _make_history_uc(4)
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history?symbol=MSFT&periods=4")

    assert resp.status_code == 200
    data = resp.json()
    assert data["period_count"] == 4
    assert len(data["periods"]) == 4

    # Verify periods param was forwarded to the use case
    history_uc.execute.assert_awaited_once()
    _, call_kwargs = history_uc.execute.call_args
    assert call_kwargs.get("periods") == 4


def test_fundamentals_history_null_fields_present() -> None:
    """Null financial fields are serialised as null (not omitted) in the response."""
    lookup_uc = _make_lookup_uc()
    history_uc = _make_history_uc_null_fields(1)
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history?symbol=MSFT")

    assert resp.status_code == 200
    data = resp.json()
    assert data["period_count"] == 1
    period = data["periods"][0]
    # Null fields must be present (not omitted) — callers check for null, not KeyError
    assert "revenue" in period
    assert period["revenue"] is None
    assert "gross_profit" in period
    assert period["gross_profit"] is None
    assert "pe_ratio" in period
    assert period["pe_ratio"] is None
    # Non-null fields still present
    assert period["eps"] == pytest.approx(1.5)


def test_fundamentals_history_response_shape() -> None:
    """Response contains expected top-level fields."""
    lookup_uc = _make_lookup_uc()
    history_uc = _make_history_uc(2)
    _, client = _make_app(lookup_uc=lookup_uc, history_uc=history_uc)

    resp = client.get("/api/v1/fundamentals/history?symbol=MSFT")

    assert resp.status_code == 200
    data = resp.json()
    assert "instrument_id" in data
    assert "ticker" in data
    assert "periods" in data
    assert "period_count" in data
    assert data["ticker"] == _TICKER
