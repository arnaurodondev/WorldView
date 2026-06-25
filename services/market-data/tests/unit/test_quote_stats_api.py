"""Unit tests for the Quote-tab statistics router (B-Q-2/3/4).

Covers GET /api/v1/instruments/{id}/{intraday-stats|returns|price-levels}:
  - 200 happy path with use-case dependency overridden
  - 404 when the use case raises InstrumentNotFoundError
  - 422 on non-UUID instrument_id (pre-DB validation)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_data.api.dependencies import (
    get_intraday_stats_uc,
    get_multi_period_returns_uc,
    get_price_levels_uc,
)
from market_data.api.routers import quote_stats as quote_stats_router
from market_data.domain.errors import InstrumentNotFoundError

pytestmark = pytest.mark.unit

_IID = "11111111-1111-1111-1111-111111111111"


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[misc]
    """Bypass the real app lifespan (no DB/Kafka in unit tests)."""
    yield


def _make_app(dep: Any, uc: Any) -> TestClient:
    app = FastAPI(lifespan=_null_lifespan)
    app.include_router(quote_stats_router.router, prefix="/api/v1")
    app.dependency_overrides[dep] = lambda: uc
    return TestClient(app)


def _uc_returning(payload: dict[str, Any]) -> AsyncMock:
    uc = AsyncMock()
    uc.execute = AsyncMock(return_value=payload)
    return uc


def _uc_raising_not_found() -> AsyncMock:
    uc = AsyncMock()
    uc.execute = AsyncMock(side_effect=InstrumentNotFoundError("Instrument not found: x"))
    return uc


# ── intraday-stats ────────────────────────────────────────────────────────────

_INTRADAY_PAYLOAD = {
    "instrument_id": _IID,
    "session_date": "2026-06-10",
    "open": 100.0,
    "prev_close": 99.0,
    "day_high": 101.0,
    "day_low": 98.5,
    "vwap": 100.2,
    "vwap_source": "1m",
    "volume": 1_000_000,
    "volume_vs_30d_ratio": 1.25,
}


def test_intraday_stats_200_shape() -> None:
    client = _make_app(get_intraday_stats_uc, _uc_returning(_INTRADAY_PAYLOAD))
    resp = client.get(f"/api/v1/instruments/{_IID}/intraday-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vwap"] == pytest.approx(100.2)
    assert body["vwap_source"] == "1m"
    assert body["volume_vs_30d_ratio"] == pytest.approx(1.25)
    assert body["prev_close"] == pytest.approx(99.0)


def test_intraday_stats_404_when_instrument_missing() -> None:
    client = _make_app(get_intraday_stats_uc, _uc_raising_not_found())
    resp = client.get(f"/api/v1/instruments/{_IID}/intraday-stats")
    assert resp.status_code == 404


def test_intraday_stats_422_on_non_uuid() -> None:
    client = _make_app(get_intraday_stats_uc, _uc_returning(_INTRADAY_PAYLOAD))
    resp = client.get("/api/v1/instruments/not-a-uuid/intraday-stats")
    assert resp.status_code == 422


# ── returns ───────────────────────────────────────────────────────────────────

_RETURNS_PAYLOAD = {
    "instrument_id": _IID,
    "as_of": "2026-06-10",
    "returns": {
        "1D": 0.5,
        "1W": 1.2,
        "1M": 3.4,
        "3M": 8.0,
        "6M": 12.0,
        "YTD": 9.9,
        "1Y": 20.0,
        "3Y": None,
        "5Y": None,
    },
}


def test_returns_200_shape_with_null_long_periods() -> None:
    client = _make_app(get_multi_period_returns_uc, _uc_returning(_RETURNS_PAYLOAD))
    resp = client.get(f"/api/v1/instruments/{_IID}/returns")
    assert resp.status_code == 200
    body = resp.json()
    assert body["returns"]["1Y"] == pytest.approx(20.0)
    # Honesty: insufficient history is null, never fabricated.
    assert body["returns"]["3Y"] is None
    assert body["returns"]["5Y"] is None


def test_returns_404_when_instrument_missing() -> None:
    client = _make_app(get_multi_period_returns_uc, _uc_raising_not_found())
    resp = client.get(f"/api/v1/instruments/{_IID}/returns")
    assert resp.status_code == 404


def test_returns_422_on_non_uuid() -> None:
    client = _make_app(get_multi_period_returns_uc, _uc_returning(_RETURNS_PAYLOAD))
    resp = client.get("/api/v1/instruments/nope/returns")
    assert resp.status_code == 422


# ── price-levels ──────────────────────────────────────────────────────────────

_LEVELS_PAYLOAD = {
    "instrument_id": _IID,
    "as_of": "2026-06-10",
    "last_close": 100.0,
    "high_52w": 120.0,
    "low_52w": 80.0,
    "pct_from_52w_high": -16.67,
    "pct_from_52w_low": 25.0,
    "ma_50": 99.0,
    "ma_200": 95.0,
    "prior_session_high": 101.0,
    "prior_session_low": 98.0,
    "support": [97.5, 95.0],
    "resistance": [102.0, 110.0],
    "sr_method": "fractal swing points (k=2) over the last 90 daily bars; ...",
}


def test_price_levels_200_shape() -> None:
    client = _make_app(get_price_levels_uc, _uc_returning(_LEVELS_PAYLOAD))
    resp = client.get(f"/api/v1/instruments/{_IID}/price-levels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["high_52w"] == pytest.approx(120.0)
    assert body["support"] == [97.5, 95.0]
    assert "fractal swing points" in body["sr_method"]


def test_price_levels_404_when_instrument_missing() -> None:
    client = _make_app(get_price_levels_uc, _uc_raising_not_found())
    resp = client.get(f"/api/v1/instruments/{_IID}/price-levels")
    assert resp.status_code == 404


def test_price_levels_422_on_non_uuid() -> None:
    client = _make_app(get_price_levels_uc, _uc_returning(_LEVELS_PAYLOAD))
    resp = client.get("/api/v1/instruments/zzz/price-levels")
    assert resp.status_code == 422
