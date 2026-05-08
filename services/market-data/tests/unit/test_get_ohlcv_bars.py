"""Unit tests for GET /api/v1/ohlcv/bars (PLAN-0066 Wave G, T-W10-G-01).

Tests cover 3-identifier resolution, date-range cap, max_bars truncation,
404 on unknown instrument, and interval pass-through.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_lookup_instrument_uc,
    get_ohlcv_bars_flexible_uc,
)
from market_data.api.routers import ohlcv as ohlcv_router
from market_data.domain.entities import Instrument, OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.errors import InstrumentNotFoundError
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority

pytestmark = pytest.mark.unit

_INSTRUMENT_UUID = str(uuid4())
_TICKER = "AAPL"
_ISIN = "US0378331005"


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


def _make_ohlcv_bar() -> OHLCVBar:
    return OHLCVBar(
        instrument_id=_INSTRUMENT_UUID,
        timeframe=Timeframe.ONE_DAY,
        bar_date=datetime(2024, 1, 15, tzinfo=UTC),
        open=Decimal("180"),
        high=Decimal("185"),
        low=Decimal("178"),
        close=Decimal("183"),
        volume=50_000_000,
        source="eodhd",
        provider_priority=ProviderPriority(provider="eodhd", priority=50),
        ingested_at=datetime.now(tz=UTC),
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


def _make_bars_flexible_uc(bars: list[OHLCVBar] | None = None) -> MagicMock:
    """Mock GetOHLCVBarsFlexibleUseCase returning a dict with "bars" and "bar_count"."""
    raw = bars or []
    result = {
        "bars": [
            {
                "date": b.bar_date.strftime("%Y-%m-%d"),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume) if b.volume is not None else 0,
            }
            for b in raw
        ],
        "bar_count": len(raw),
    }
    uc = MagicMock()
    uc.execute = AsyncMock(return_value=result)
    return uc


def _make_app(
    lookup_uc: MagicMock | None = None,
    bars_uc: MagicMock | None = None,
) -> tuple[FastAPI, TestClient]:
    app = FastAPI(lifespan=_null_lifespan)
    # Provide a settings object with ohlcv_max_days in app state
    settings_mock = MagicMock()
    settings_mock.ohlcv_max_days = 365
    app.state.settings = settings_mock
    app.include_router(ohlcv_router.router, prefix="/api/v1")

    if lookup_uc is not None:
        app.dependency_overrides[get_lookup_instrument_uc] = lambda: lookup_uc
    if bars_uc is not None:
        app.dependency_overrides[get_ohlcv_bars_flexible_uc] = lambda: bars_uc

    return app, TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_ohlcv_bars_resolves_by_symbol() -> None:
    """GET /ohlcv/bars?symbol=AAPL → lookup called with symbol=AAPL."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc([_make_ohlcv_bar()])
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get("/api/v1/ohlcv/bars?symbol=AAPL&from_date=2024-01-01&to_date=2024-03-31")

    assert resp.status_code == 200
    # Verify lookup was called with symbol
    lookup_uc.execute.assert_awaited_once()
    _, call_kwargs = lookup_uc.execute.call_args
    assert call_kwargs.get("symbol") == "AAPL"
    assert call_kwargs.get("id") is None


def test_ohlcv_bars_resolves_by_isin() -> None:
    """GET /ohlcv/bars?isin=... → lookup called with isin."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc([_make_ohlcv_bar()])
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get(f"/api/v1/ohlcv/bars?isin={_ISIN}&from_date=2024-01-01&to_date=2024-03-31")

    assert resp.status_code == 200
    _, call_kwargs = lookup_uc.execute.call_args
    assert call_kwargs.get("isin") == _ISIN
    assert call_kwargs.get("symbol") is None


def test_ohlcv_bars_returns_400_if_no_identifier() -> None:
    """GET /ohlcv/bars with no identifier → HTTP 400."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc()
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get("/api/v1/ohlcv/bars?from_date=2024-01-01&to_date=2024-03-31")

    assert resp.status_code == 400
    assert "instrument_id" in resp.json()["detail"].lower() or "required" in resp.json()["detail"].lower()


def test_ohlcv_bars_returns_404_if_not_found() -> None:
    """GET /ohlcv/bars with unknown symbol → HTTP 404."""
    lookup_uc = _make_lookup_uc(raise_not_found=True)
    bars_uc = _make_bars_flexible_uc()
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get("/api/v1/ohlcv/bars?symbol=UNKNOWN&from_date=2024-01-01&to_date=2024-03-31")

    assert resp.status_code == 404


def test_ohlcv_bars_rejects_excessive_date_range() -> None:
    """Date range > max_days (365) → HTTP 422."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc()
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    # 366 days > 365 cap
    resp = client.get("/api/v1/ohlcv/bars?symbol=AAPL&from_date=2023-01-01&to_date=2024-01-02")

    assert resp.status_code == 422
    assert "maximum" in resp.json()["detail"].lower() or "days" in resp.json()["detail"].lower()


def test_ohlcv_bars_weekly_resampling() -> None:
    """GET /ohlcv/bars?interval=week → interval forwarded to use case."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc([_make_ohlcv_bar()])
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get("/api/v1/ohlcv/bars?symbol=AAPL&from_date=2024-01-01&to_date=2024-06-30&interval=week")

    assert resp.status_code == 200
    # Verify the interval is echoed in the response
    data = resp.json()
    assert data["interval"] == "week"


def test_ohlcv_bars_max_bars_truncation() -> None:
    """GET /ohlcv/bars?max_bars=2 → at most 2 bars returned."""
    # Use case is mocked to return only what it's given — truncation happens inside use case
    # Here we test that max_bars is forwarded to the use case call
    lookup_uc = _make_lookup_uc()

    uc = MagicMock()
    # Return only 2 bars regardless (simulating use-case truncation)
    uc.execute = AsyncMock(
        return_value={
            "bars": [
                {"date": "2024-01-01", "open": 180.0, "high": 185.0, "low": 178.0, "close": 183.0, "volume": 1000},
                {"date": "2024-01-02", "open": 183.0, "high": 186.0, "low": 181.0, "close": 184.0, "volume": 1500},
            ],
            "bar_count": 2,
        }
    )

    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=uc)

    resp = client.get("/api/v1/ohlcv/bars?symbol=AAPL&from_date=2024-01-01&to_date=2024-06-30&max_bars=2")

    assert resp.status_code == 200
    data = resp.json()
    assert data["bar_count"] == 2

    # Verify max_bars was forwarded to the use case
    uc.execute.assert_awaited_once()
    _, call_kwargs = uc.execute.call_args
    assert call_kwargs.get("max_bars") == 2


def test_ohlcv_bars_response_shape() -> None:
    """Response contains expected fields: instrument_id, ticker, interval, bars, bar_count."""
    lookup_uc = _make_lookup_uc()
    bars_uc = _make_bars_flexible_uc([_make_ohlcv_bar()])
    _, client = _make_app(lookup_uc=lookup_uc, bars_uc=bars_uc)

    resp = client.get("/api/v1/ohlcv/bars?symbol=AAPL&from_date=2024-01-01&to_date=2024-03-31")

    assert resp.status_code == 200
    data = resp.json()
    assert "instrument_id" in data
    assert "ticker" in data
    assert "interval" in data
    assert "bars" in data
    assert "bar_count" in data
    assert data["ticker"] == _TICKER
    assert data["interval"] == "day"
