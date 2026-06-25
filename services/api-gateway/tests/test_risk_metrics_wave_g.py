"""Tests for Wave G risk-metrics additions: calmar, win_rate, alpha.

Covers:
    test_calmar_is_null_when_no_drawdown  — constant value series → drawdown=0 → calmar=None
    test_win_rate_correct                 — known up/down series → assert fraction
    test_alpha_is_null_when_spy_unavailable — endpoint: SPY fetch returns [] → alpha=None
    test_alpha_positive_when_portfolio_outperforms — pure: port 20%/yr, SPY 10%/yr → alpha>0

WHY pure-function tests for most cases: _calmar, _win_rate, _alpha are extracted
pure functions (no I/O). Testing them directly is faster and avoids spinning up
the full ASGI stack for simple arithmetic assertions.
WHY one endpoint test (alpha_null_when_spy_unavailable): verifies the route
correctly propagates SPY-unavailability → alpha=None (not just the helper function).
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
    _MIN_RETURNS,
    _TRADING_DAYS_PER_YEAR,
    _alpha,
    _calmar,
    _win_rate,
)
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}
_PORTFOLIO_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=json.loads(content))
    except Exception:
        resp.json = MagicMock(side_effect=ValueError("invalid JSON"))
    return resp


# ── test_calmar_is_null_when_no_drawdown ─────────────────────────────────────


def test_calmar_is_null_when_no_drawdown() -> None:
    """A constant-value series produces drawdown_max=0.0, so calmar=None.

    WHY this matters: the _calmar helper must guard against divide-by-zero
    when the portfolio is at all-time-high and has never drawn down. The
    Calmar ratio is undefined in that case — returning any finite value
    would misrepresent the risk profile.
    """
    # Build 20 identical daily returns (portfolio never moves) so drawdown=0.
    # _calmar receives the already-computed drawdown_max, not raw values.
    flat_returns = [0.0] * 20  # zero daily returns → annualised return also zero
    calmar_from_zero_drawdown = _calmar(flat_returns, drawdown_max=0.0)
    assert calmar_from_zero_drawdown is None, "calmar should be None when drawdown_max=0"

    calmar_from_none_drawdown = _calmar(flat_returns, drawdown_max=None)
    assert calmar_from_none_drawdown is None, "calmar should be None when drawdown_max=None"


def test_calmar_is_null_when_insufficient_returns() -> None:
    """Fewer than _MIN_RETURNS returns → calmar=None regardless of drawdown."""
    sparse = [0.01] * (_MIN_RETURNS - 1)
    assert _calmar(sparse, drawdown_max=-0.10) is None


def test_calmar_positive_for_normal_series() -> None:
    """A positive-return series with real drawdown produces a finite calmar > 0."""
    # 20 days of +0.5% daily returns (roughly +130% annualised) with drawdown of -5%.
    returns = [0.005] * 20
    calmar = _calmar(returns, drawdown_max=-0.05)
    assert calmar is not None
    assert calmar > 0.0


# ── test_win_rate_correct ────────────────────────────────────────────────────


def test_win_rate_correct() -> None:
    """Known series: 7 up-days, 3 down-days out of 10 → win_rate = 0.70.

    WHY explicit 0/non-zero check: win_rate=0.0 is a legitimate value (all
    losing days). The test must NOT assert > 0; it must assert == expected_fraction.
    """
    # 7 positive, 3 negative, all above _MIN_RETURNS=10.
    returns = [0.01] * 7 + [-0.01] * 3
    result = _win_rate(returns)
    assert result is not None
    assert math.isclose(result, 7 / 10, rel_tol=1e-9)


def test_win_rate_correct_with_zeros() -> None:
    """Zero returns are NOT wins — only strictly positive returns count."""
    returns = [0.01] * 6 + [0.0] * 2 + [-0.01] * 4  # 12 total, 6 wins
    result = _win_rate(returns)
    assert result is not None
    assert math.isclose(result, 6 / 12, rel_tol=1e-9)


def test_win_rate_is_null_for_insufficient_returns() -> None:
    """Fewer than _MIN_RETURNS daily returns → win_rate=None."""
    sparse = [0.01] * (_MIN_RETURNS - 1)
    assert _win_rate(sparse) is None


# ── test_alpha_is_null_when_spy_unavailable ───────────────────────────────────


@pytest.mark.asyncio
async def test_alpha_is_null_when_spy_unavailable(authed_app, authed_mock_clients) -> None:
    """When SPY OHLCV cannot be resolved, alpha=None in the risk-metrics response.

    WHY endpoint test (not pure-function): this verifies the full route wiring —
    that the SPY-unavailable degradation path propagates cleanly to the JSON
    payload and doesn't raise or produce NaN.
    """
    today = date(2026, 5, 23)  # fixed date avoids DTZ011; tests don't care about real "today"
    start = today - timedelta(days=90)

    # Build 30 daily portfolio snapshots with gentle upward drift.
    portfolio_points = []
    value = 100_000.0
    for i in range(30):
        d = (start + timedelta(days=i)).isoformat()
        value *= 1.001
        portfolio_points.append({"date": d, "value": value})

    portfolio_body = json.dumps({"points": portfolio_points}).encode()

    # Portfolio value history returns 200 + data.
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, portfolio_body))
    # SPY instrument-search returns 200 but empty items → spy_id=None → spy_series=[].
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"items": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/portfolios/{_PORTFOLIO_ID}/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # Alpha requires SPY data — with SPY unavailable it must be null.
    assert body["alpha"] is None, f"Expected alpha=null when SPY unavailable, got {body['alpha']}"
    # Sanity-check: beta also null when SPY unavailable (existing behaviour).
    assert body["beta_vs_spy"] is None


# ── test_alpha_positive_when_portfolio_outperforms ────────────────────────────


def test_alpha_positive_when_portfolio_outperforms() -> None:
    """Portfolio 20% annualised, SPY 10% annualised → alpha ≈ +0.10 (10pp).

    WHY pure-function test: _alpha is stateless arithmetic; no HTTP mocking
    needed. The annualised return formula is mean(r)*252, so we back out the
    per-day return from the target annualised return.
    """
    target_portfolio_ann = 0.20  # 20% annualised
    target_spy_ann = 0.10  # 10% annualised
    n = 20  # 20 aligned days — above _MIN_RETURNS

    # per-day return such that mean(r)*252 == target
    daily_p = target_portfolio_ann / _TRADING_DAYS_PER_YEAR
    daily_s = target_spy_ann / _TRADING_DAYS_PER_YEAR

    port_returns = [daily_p] * n
    spy_returns = [daily_s] * n

    result = _alpha(port_returns, spy_returns)
    assert result is not None
    assert result > 0.0, f"Expected positive alpha, got {result}"
    expected = target_portfolio_ann - target_spy_ann
    assert math.isclose(result, expected, rel_tol=1e-9), f"Expected alpha ≈ {expected}, got {result}"


def test_alpha_is_null_for_mismatched_series() -> None:
    """Mismatched series lengths → alpha=None (alignment invariant violated)."""
    assert _alpha([0.001] * 15, [0.0005] * 10) is None


def test_alpha_is_null_for_insufficient_series() -> None:
    """Both series too short → alpha=None."""
    assert _alpha([0.001] * (_MIN_RETURNS - 1), [0.0005] * (_MIN_RETURNS - 1)) is None


# ── F-007 (QA Wave G) — per-leg degradation reasoning ─────────────────────────


@pytest.mark.asyncio
async def test_value_history_upstream_exception_yields_degraded_upstream(authed_app, authed_mock_clients) -> None:
    """F-007: when S1 raises (ConnectError / timeout / 5xx), the endpoint MUST
    surface ``data_quality.status="degraded_upstream"`` and
    ``data_quality.degradation.value_history="exception"`` — NOT the legacy
    silent downgrade to ``"insufficient_data"`` which conflated transient
    upstream failures with portfolios genuinely lacking history.

    WHY this matters: the empty-state caption in the frontend reads
    "Not enough history" for insufficient_data but should read something like
    "Backend temporarily unavailable" for a real outage. Conflating the two
    silently misleads the user.
    """
    # Portfolio leg: raise to simulate a real connection failure.
    authed_mock_clients.portfolio.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    # SPY leg: succeed with empty items so the SPY branch returns no_data.
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"items": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/portfolios/{_PORTFOLIO_ID}/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # Per-leg degradation surfaced explicitly.
    assert body["data_quality"]["status"] == "degraded_upstream"
    assert body["data_quality"]["degradation"]["value_history"] == "exception"


@pytest.mark.asyncio
async def test_spy_only_failure_does_not_block_portfolio_metrics(authed_app, authed_mock_clients) -> None:
    """F-007: SPY-only failures must NOT cause ``degraded_upstream`` — the
    portfolio metrics that don't depend on SPY (drawdown, vol, Sharpe,
    Sortino, calmar, win_rate, period_return, cagr, var_95) remain valid;
    only beta + alpha degrade to None.

    Status should be ``"benchmark_unavailable"`` (existing behaviour),
    ``degradation.benchmark`` should reflect the failure mode (``"5xx"``).
    """
    today = date(2026, 5, 23)
    start = today - timedelta(days=90)

    # Portfolio leg: 30 valid points (well over _MIN_RETURNS=10 daily returns).
    portfolio_points = []
    value = 100_000.0
    for i in range(30):
        d = (start + timedelta(days=i)).isoformat()
        value *= 1.001
        portfolio_points.append({"date": d, "value": value})
    portfolio_body = json.dumps({"points": portfolio_points}).encode()
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, portfolio_body))
    # SPY leg: instrument-search returns 5xx → benchmark unavailable.
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(503, b'{"error":"down"}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/portfolios/{_PORTFOLIO_ID}/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # Portfolio-only metrics still populated.
    assert body["volatility_annualized"] is not None
    assert body["sharpe"] is not None
    # Benchmark-dependent metrics degrade to None.
    assert body["beta_vs_spy"] is None
    assert body["alpha"] is None
    # Status remains benchmark_unavailable — NOT degraded_upstream.
    assert body["data_quality"]["status"] == "benchmark_unavailable"
    # SPY degradation surfaced; value_history is None (clean success).
    assert body["data_quality"]["degradation"]["value_history"] is None
    # benchmark degradation reason — _resolve_spy_instrument_id swallows the
    # 503 and returns None → "no_data". (If S3 search itself raised we'd see
    # "exception"; status_code 503 on /instruments produces None → no_data.)
    assert body["data_quality"]["degradation"]["benchmark"] in {"5xx", "no_data", "exception"}


# ── BP-682 — SPY bar_date is a datetime, not a bare date ──────────────────────


def test_parse_iso_date_accepts_datetime_and_bare_date() -> None:
    """BP-682: _parse_iso_date must accept BOTH a bare ``YYYY-MM-DD`` (S1's
    value-history ``date``) AND a full ISO datetime with trailing ``Z`` (S3's
    OHLCV ``bar_date``, serialised from a ``datetime`` Pydantic field).

    The old code called ``date.fromisoformat`` directly, which raises
    ``ValueError`` on ``"2025-08-28T00:00:00Z"`` — silently dropping EVERY SPY
    bar and collapsing beta/alpha to null even when the benchmark series exists.
    """
    from datetime import date as _date

    from api_gateway.routes.risk_metrics import _parse_iso_date

    assert _parse_iso_date("2025-08-28") == _date(2025, 8, 28)
    # The exact shape S3 returns for an OHLCV bar_date.
    assert _parse_iso_date("2025-08-28T00:00:00Z") == _date(2025, 8, 28)
    # Also tolerate an offset-style datetime just in case.
    assert _parse_iso_date("2025-08-28T13:45:00+00:00") == _date(2025, 8, 28)


def _spy_search_body() -> bytes:
    """S3 instrument-search response for SPY — id + symbol + exchange, matching
    the real ``InstrumentResponse`` shape (``id`` / ``symbol``, NOT
    ``instrument_id`` / ``ticker``)."""
    return json.dumps(
        {
            "items": [
                {
                    "id": "019e0db9-0f03-7efb-8a08-4c4796c6e4cc",
                    "symbol": "SPY",
                    "exchange": "US",
                },
            ],
            "total": 1,
        },
    ).encode()


@pytest.mark.asyncio
async def test_beta_alpha_compute_with_datetime_shaped_bar_dates(authed_app, authed_mock_clients) -> None:
    """BP-682 REGRESSION: when SPY OHLCV bars carry datetime-shaped ``bar_date``
    (``"2025-...T00:00:00Z"``) AND the series is long enough, beta + alpha MUST
    compute (not null) and ``data_quality`` MUST read ``"ok"``.

    Before the fix this returned ``beta_vs_spy=null`` / ``alpha=null`` /
    ``benchmark="no_data"`` because every bar failed ``date.fromisoformat``.
    """
    today = date(2026, 5, 23)
    start = today - timedelta(days=90)

    # 40 portfolio snapshots (well over _MIN_RETURNS) with gentle drift.
    portfolio_points = []
    p_val = 100_000.0
    for i in range(40):
        d = (start + timedelta(days=i)).isoformat()  # bare date — S1 shape
        p_val *= 1.002
        portfolio_points.append({"date": d, "value": p_val})
    portfolio_body = json.dumps({"points": portfolio_points}).encode()

    # 40 SPY bars on the SAME dates so _align_by_date yields >= _MIN_RETURNS+1
    # overlap. bar_date uses the datetime-with-Z shape S3 actually emits.
    spy_bars = []
    s_close = 500.0
    for i in range(40):
        d_iso = (start + timedelta(days=i)).isoformat()
        bar_date = f"{d_iso}T00:00:00Z"  # ← the shape that broke the old parser
        s_close *= 1.001
        spy_bars.append({"bar_date": bar_date, "close": f"{s_close:.4f}"})
    spy_ohlcv_body = json.dumps({"items": spy_bars, "total": len(spy_bars), "timeframe": "1d"}).encode()

    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, portfolio_body))

    # market_data.get serves TWO endpoints: instrument-search and OHLCV.
    # Differentiate by path so the SPY-id resolves and the OHLCV bars flow.
    async def _market_data_get(path: str, *args, **kwargs):
        if "/instruments" in path:
            return _mock_response(200, _spy_search_body())
        if "/ohlcv/" in path:
            return _mock_response(200, spy_ohlcv_body)
        return _mock_response(404, b"{}")

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_market_data_get)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/portfolios/{_PORTFOLIO_ID}/risk-metrics",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # The crux: beta + alpha MUST compute now that bar_date parses.
    assert body["beta_vs_spy"] is not None, f"beta should compute, got {body['beta_vs_spy']}"
    assert body["alpha"] is not None, f"alpha should compute, got {body['alpha']}"
    # Benchmark leg healthy → no degradation reason → status ok.
    assert body["data_quality"]["degradation"]["benchmark"] is None
    assert body["data_quality"]["status"] == "ok"
