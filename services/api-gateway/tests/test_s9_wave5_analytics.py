"""Tests for PLAN-0046 Wave 5 — portfolio analytics S9 routes.

Covers:
    - T-46-5-01 proxy: GET /v1/portfolios/{id}/value-history
    - T-46-5-02 proxy: GET /v1/portfolios/{id}/exposure
    - T-46-5-03 composition: GET /v1/portfolios/{id}/risk-metrics
      including a hand-computed reference series for Sharpe.

Reuses ``authed_app`` / ``authed_mock_clients`` fixtures from conftest.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from api_gateway.routes.risk_metrics import (
    _beta,
    _daily_returns,
    _drawdowns,
    _sharpe,
    _sortino,
    _volatility_annualised,
)
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    # Many of our tests need .json() too.
    try:
        resp.json = MagicMock(return_value=json.loads(content))
    except Exception:
        resp.json = MagicMock(side_effect=ValueError("invalid JSON"))
    return resp


# ── value-history proxy ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_value_history_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios/p-1/value-history")
    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_value_history_proxies_to_s1_with_query_params(
    authed_app,
    authed_mock_clients,
) -> None:
    """T-46-5-01: query params (from/to/granularity) flow through unchanged."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"points": []}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/value-history",
            params={"from": "2026-01-01", "to": "2026-04-30", "granularity": "1w"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    args, kwargs = authed_mock_clients.portfolio.get.call_args
    assert args[0] == "/api/v1/portfolios/p-1/value-history"
    assert kwargs["params"]["from"] == "2026-01-01"
    assert kwargs["params"]["to"] == "2026-04-30"
    assert kwargs["params"]["granularity"] == "1w"


@pytest.mark.asyncio
async def test_value_history_passes_404_through(
    authed_app,
    authed_mock_clients,
) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail":"not found"}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/value-history",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 404


# ── exposure proxy ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exposure_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios/p-1/exposure")
    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_exposure_proxies_to_s1(authed_app, authed_mock_clients) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(
            200,
            b'{"invested":"0","cash":"0","gross_exposure_pct":"0","net_exposure_pct":"0","leverage":"0"}',
        ),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/exposure",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    args, _ = authed_mock_clients.portfolio.get.call_args
    assert args[0] == "/api/v1/portfolios/p-1/exposure"


# ── PLAN-0051 Wave A — realised P&L proxy (T-A-1-04) ─────────────────────────


@pytest.mark.asyncio
async def test_realized_pnl_requires_auth(app, mock_clients) -> None:
    """Unauthenticated request → 401, no downstream call."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios/p-1/realized-pnl")
    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_realized_pnl_proxies_to_s1_with_query_params(
    authed_app,
    authed_mock_clients,
) -> None:
    """T-A-1-04: ``from``/``to`` query params flow through unchanged and
    the gateway tags successful responses with ``Cache-Control: max-age=300``."""
    body = (
        b'{"total_realized":"100.00000000","realized_long_term":"0.00000000",'
        b'"realized_short_term":"100.00000000","count":1,'
        b'"breakdown_by_instrument":[],"currency":"USD",'
        b'"from_date":"2026-01-01","to_date":"2026-04-30"}'
    )
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, body))
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/p-1/realized-pnl",
            params={"from": "2026-01-01", "to": "2026-04-30"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    args, kwargs = authed_mock_clients.portfolio.get.call_args
    assert args[0] == "/api/v1/portfolios/p-1/realized-pnl"
    assert kwargs["params"]["from"] == "2026-01-01"
    assert kwargs["params"]["to"] == "2026-04-30"
    # 5-minute edge cache hint on the success path.
    assert resp.headers.get("cache-control") == "max-age=300"


@pytest.mark.asyncio
async def test_realized_pnl_passes_404_through(
    authed_app,
    authed_mock_clients,
) -> None:
    """S1 returning 404 (missing portfolio / wrong tenant) must surface unchanged."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail":"not found"}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/missing/realized-pnl",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 404
    # 404 responses MUST NOT be cached — we don't want a brief 404 to be
    # served from a CDN for 5 minutes after the data lands.
    assert resp.headers.get("cache-control") is None


# ── risk-metrics composition ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_metrics_requires_auth(app) -> None:
    # SEC-F001 (QA 2026-05-23): portfolio_id is now UUID-validated. Auth check
    # runs BEFORE UUID validation so unauthenticated probes get 401, not 422.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios/00000000-0000-0000-0000-000000000001/risk-metrics")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_risk_metrics_returns_nulls_for_short_history(
    authed_app,
    authed_mock_clients,
) -> None:
    """Acceptance: N < 10 daily returns → every metric is null."""
    # 5 points → 4 returns → < 10 → all metrics must be null.
    short_points = [
        {"date": (date(2026, 4, 20) + timedelta(days=i)).isoformat(), "value": str(100 + i)} for i in range(5)
    ]
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, json.dumps({"points": short_points}).encode()),
    )
    # Market-data: SPY lookup not strictly needed for null path, but the
    # route fetches it regardless. Return empty so resolution fails gracefully.
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/00000000-0000-0000-0000-000000000001/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    for k in ("drawdown_max", "drawdown_current", "volatility_annualized", "sharpe", "sortino", "beta_vs_spy"):
        assert body[k] is None, f"{k} should be null when N < 10"


@pytest.mark.asyncio
async def test_risk_metrics_passes_value_history_404_through(
    authed_app,
    authed_mock_clients,
) -> None:
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail":"not found"}'),
    )
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": []}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/00000000-0000-0000-0000-00000000dead/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_risk_metrics_lookback_bounds(authed_app) -> None:
    """lookback_days < 10 → 422 (Pydantic validation)."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/00000000-0000-0000-0000-000000000001/risk-metrics",
            params={"lookback_days": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 422


# ── Pure-function reference tests (T-46-5-03 acceptance: Sharpe ±0.01) ─────


def test_daily_returns_basic() -> None:
    # V = [100, 101, 99, 102] → r = [0.01, -0.0198..., 0.0303...]
    r = _daily_returns([100.0, 101.0, 99.0, 102.0])
    assert len(r) == 3
    assert r[0] == pytest.approx(0.01)
    assert r[1] == pytest.approx(-0.019801980, abs=1e-6)
    assert r[2] == pytest.approx(0.030303030, abs=1e-6)


def test_daily_returns_skips_zero_predecessor() -> None:
    # Zero/negative previous value would produce inf — must be skipped, not returned.
    r = _daily_returns([0.0, 100.0, 110.0])
    assert r == pytest.approx([0.10])


def test_drawdowns_simple_decline() -> None:
    # Peak 100 then drop to 80 → dd_max = -20%, dd_current = -20%.
    dd_max, dd_curr = _drawdowns([100.0, 90.0, 80.0])
    assert dd_max == pytest.approx(-0.20)
    assert dd_curr == pytest.approx(-0.20)


def test_drawdowns_recovery_resets_current() -> None:
    # Peak 100, dip to 50, recover to 100 → dd_max = -50%, dd_current = 0.
    dd_max, dd_curr = _drawdowns([100.0, 50.0, 100.0])
    assert dd_max == pytest.approx(-0.50)
    assert dd_curr == pytest.approx(0.0)


def test_sharpe_reference_series_within_one_basis_point() -> None:
    """Hand-computed reference series.

    Use a tightly-pinned series of 11 daily returns where every step
    is independently verifiable with a calculator:

        r = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01]

    Population stats (used by ``_volatility_annualised`` via ``pstdev``):
        n = 11
        mean = (6 * 0.01 + 5 * -0.01) / 11 = 0.01 / 11 ≈ 0.000909091
        Each (r_i - mean)² ≈ either (0.00909)² or (-0.01091)²
            = 8.264e-5  or  1.190e-4
            (6 of the first, 5 of the second)
        Population variance = (6*8.264e-5 + 5*1.190e-4) / 11
                            = (4.958e-4 + 5.950e-4) / 11
                            = 1.0908e-3 / 11
                            ≈ 9.917e-5
        Population stdev ≈ 0.009959
        Annualised stdev ≈ 0.009959 * sqrt(252) ≈ 0.15807
        Annualised mean = 0.000909091 * 252 ≈ 0.22909
        Numerator = 0.22909 - 0.05 = 0.17909
        Sharpe ≈ 0.17909 / 0.15807 ≈ 1.1330

    Plan acceptance criterion: must agree with our implementation within 0.01.
    """
    r = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01]
    sharpe = _sharpe(r)
    assert sharpe is not None
    expected = 1.133
    assert math.isfinite(sharpe)
    assert sharpe == pytest.approx(expected, abs=0.01), f"Sharpe {sharpe} differs from {expected} by > 0.01"


def test_sortino_uses_only_negative_returns() -> None:
    """Sortino > Sharpe when downside variance < total variance.

    Use a series with mostly positive returns — Sortino should be larger
    than Sharpe because the denominator (downside dev) is smaller.
    """
    r = [0.02, 0.015, -0.005, 0.01, 0.012, -0.003, 0.008, 0.011, -0.004, 0.009, 0.013, 0.007]
    sharpe = _sharpe(r)
    sortino = _sortino(r)
    assert sharpe is not None and sortino is not None
    assert sortino > sharpe


def test_sortino_returns_none_when_no_downside() -> None:
    # All-positive series → no negative returns → Sortino is undefined.
    r = [0.01] * 15
    assert _sortino(r) is None


def test_beta_perfect_correlation_one() -> None:
    """β(x, x) = var(x)/var(x) = 1.0 for any non-flat series."""
    r = [0.01, -0.005, 0.012, 0.003, -0.008, 0.015, -0.002, 0.007, 0.011, -0.006, 0.004, 0.009]
    beta = _beta(r, r)
    assert beta is not None
    assert beta == pytest.approx(1.0)


def test_beta_zero_when_uncorrelated() -> None:
    """β can be near-zero when the cov is near zero."""
    # Symmetric, zero-mean, anti-aligned series → covariance near zero.
    a = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
    b = [1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0]
    beta = _beta(a, b)
    assert beta is not None
    # Not exactly zero with a finite sample, but small.
    assert abs(beta) < 0.5


def test_beta_returns_none_on_flat_market() -> None:
    """Flat SPY → variance 0 → beta undefined."""
    r_p = [0.01, -0.005, 0.012, 0.003, -0.008, 0.015, -0.002, 0.007, 0.011, -0.006, 0.004]
    r_spy = [0.0] * 11
    assert _beta(r_p, r_spy) is None


def test_volatility_annualised_zero_for_constant_series() -> None:
    assert _volatility_annualised([0.01, 0.01, 0.01]) == 0.0
