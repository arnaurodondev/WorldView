"""Tests for the B-Q backend wave routes (2026-06-10).

Covers:
  - GET /v1/instruments/{id}/intraday-stats   (B-Q-2 proxy → S3)
  - GET /v1/instruments/{id}/returns          (B-Q-3 proxy → S3)
  - GET /v1/instruments/{id}/price-levels     (B-Q-4 proxy → S3)
  - GET /v1/companies/by-ticker/{ticker}/overview (task 6)
  - GET /v1/fundamentals/{id}/balance-sheet   (task 7 proxy)
  - GET /v1/fundamentals/{id}/cash-flow       (task 7 proxy)
  - bid/ask mapping in _map_price_snapshot_to_quote (task 5)

Follows the test_w5_computed_routes.py conventions (authed_app fixtures).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}

_INSTRUMENT_UUID = "11111111-1111-1111-1111-111111111111"


def _make_jwt() -> str:
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_jwt()}"}


def _mock_http_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content.decode()
    try:
        resp.json.return_value = json.loads(content)
    except json.JSONDecodeError:
        resp.json.side_effect = ValueError("invalid JSON")
    return resp


@pytest.fixture(autouse=True)
def _clear_resolution_cache():
    """resolve_security_id caches per-process for 1h — isolate tests."""
    from api_gateway.resolution import _resolution_cache

    _resolution_cache.clear()
    yield
    _resolution_cache.clear()


# ── B-Q-2/3/4 instrument stat proxies ─────────────────────────────────────────


@pytest.mark.parametrize("suffix", ["intraday-stats", "returns", "price-levels"])
@pytest.mark.asyncio
async def test_instrument_stat_proxies_require_auth(authed_app, suffix) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/instruments/{_INSTRUMENT_UUID}/{suffix}")
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("suffix", "s3_body"),
    [
        (
            "intraday-stats",
            {"instrument_id": _INSTRUMENT_UUID, "vwap": 100.2, "prev_close": 99.0, "volume_vs_30d_ratio": 1.1},
        ),
        (
            "returns",
            {"instrument_id": _INSTRUMENT_UUID, "as_of": "2026-06-10", "returns": {"1D": 0.5, "5Y": None}},
        ),
        (
            "price-levels",
            {"instrument_id": _INSTRUMENT_UUID, "high_52w": 120.0, "support": [97.5], "resistance": [102.0]},
        ),
    ],
)
@pytest.mark.asyncio
async def test_instrument_stat_proxies_forward_to_s3(authed_app, authed_mock_clients, suffix, s3_body) -> None:
    """Each proxy forwards to S3's /api/v1/instruments/{uuid}/<suffix> verbatim."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, json.dumps(s3_body).encode()))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/instruments/{_INSTRUMENT_UUID}/{suffix}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json() == s3_body
    called_path = authed_mock_clients.market_data.get.call_args.args[0]
    assert called_path == f"/api/v1/instruments/{_INSTRUMENT_UUID}/{suffix}"


@pytest.mark.asyncio
async def test_instrument_stat_proxy_passes_through_404(authed_app, authed_mock_clients) -> None:
    """S3 404 (unknown instrument) is passed through, not converted to 500."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_http_response(404, b'{"detail": "Instrument not found"}')
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/instruments/{_INSTRUMENT_UUID}/returns", headers=_auth_headers())
    assert resp.status_code == 404


# ── Task 6: by-ticker overview ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_by_ticker_overview_requires_auth(authed_app) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/companies/by-ticker/AAPL/overview")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_by_ticker_overview_resolves_then_composes(authed_app, authed_mock_clients) -> None:
    """Ticker → S3 lookup → CompanyOverviewUseCase with the resolved UUID."""
    lookup_body = json.dumps({"id": _INSTRUMENT_UUID, "symbol": "AAPL", "exchange": "US"}).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, lookup_body))

    overview = {"instrument": {"id": _INSTRUMENT_UUID, "symbol": "AAPL"}, "quote": {"price": 315.2}}
    with patch(
        "api_gateway.application.use_cases.company_overview.CompanyOverviewUseCase.execute",
        new=AsyncMock(return_value=overview),
    ) as mock_execute:
        transport = ASGITransport(app=authed_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/companies/by-ticker/AAPL/overview", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json() == overview
    # The use case must receive the RESOLVED UUID, never the raw ticker.
    assert mock_execute.call_args.kwargs["company_id"] == _INSTRUMENT_UUID
    # The S3 lookup was called with the upper-cased symbol.
    lookup_call = authed_mock_clients.market_data.get.call_args
    assert lookup_call.args[0] == "/api/v1/instruments/lookup"
    assert lookup_call.kwargs["params"]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_by_ticker_overview_404_for_unknown_ticker(authed_app, authed_mock_clients) -> None:
    """Both S3 lookup and KG alias fallback miss → 404 (never 500)."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(404, b"{}"))
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_http_response(404, b"{}"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/companies/by-ticker/ZZZZZZ/overview", headers=_auth_headers())
    assert resp.status_code == 404


# ── Task 7: balance-sheet + cash-flow proxies ────────────────────────────────


@pytest.mark.parametrize("section", ["balance-sheet", "cash-flow"])
@pytest.mark.asyncio
async def test_statement_proxies_require_auth(authed_app, section) -> None:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}/{section}")
    assert resp.status_code == 401


@pytest.mark.parametrize("section", ["balance-sheet", "cash-flow"])
@pytest.mark.asyncio
async def test_statement_proxies_forward_to_s3(authed_app, authed_mock_clients, section) -> None:
    s3_body = json.dumps(
        {"security_id": _INSTRUMENT_UUID, "records": [{"section": section.replace("-", "_"), "data": {}}]}
    ).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, s3_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{_INSTRUMENT_UUID}/{section}", headers=_auth_headers())

    assert resp.status_code == 200
    assert resp.json()["security_id"] == _INSTRUMENT_UUID
    called_path = authed_mock_clients.market_data.get.call_args.args[0]
    assert called_path == f"/api/v1/fundamentals/{_INSTRUMENT_UUID}/{section}"


# ── Task 5: bid/ask mapping in the quote shape ───────────────────────────────


def test_map_price_snapshot_to_quote_includes_bid_ask() -> None:
    """S3's string-typed bid/ask survive the snapshot→quote mapping as floats."""
    from api_gateway.routes.market import _map_price_snapshot_to_quote

    snap = {
        "instrument_id": _INSTRUMENT_UUID,
        "symbol": "AAPL",
        "price": "315.20",
        "price_change": "1.50",
        "price_change_pct": "0.48",
        "timestamp": "2026-06-10T14:00:00+00:00",
        "source": "fresh_quote",
        "freshness_status": "live",
        "bid": "315.10",
        "ask": "315.30",
    }
    quote = _map_price_snapshot_to_quote(snap, _INSTRUMENT_UUID)
    assert quote["bid"] == pytest.approx(315.10)
    assert quote["ask"] == pytest.approx(315.30)


def test_map_price_snapshot_to_quote_bid_ask_null_when_absent() -> None:
    """Bar-sourced snapshots (or pre-bid/ask S3) yield null bid/ask — never 0."""
    from api_gateway.routes.market import _map_price_snapshot_to_quote

    snap = {
        "instrument_id": _INSTRUMENT_UUID,
        "symbol": "AAPL",
        "price": "315.20",
        "timestamp": "2026-06-10T14:00:00+00:00",
        "source": "daily_close",
        "freshness_status": "delayed",
        # no bid/ask keys at all (legacy S3 response)
    }
    quote = _map_price_snapshot_to_quote(snap, _INSTRUMENT_UUID)
    assert quote["bid"] is None
    assert quote["ask"] is None


# ── Backend-gaps wave 3 (2026-06-11): previous_close in the quote shape ──────


def test_map_price_snapshot_to_quote_includes_previous_close() -> None:
    """previous_close = price - change (exact inverse of S3's formula)."""
    from api_gateway.routes.market import _map_price_snapshot_to_quote

    snap = {
        "instrument_id": _INSTRUMENT_UUID,
        "symbol": "AAPL",
        "price": "291.58",
        "price_change": "1.03",
        "price_change_pct": "0.3545",
        "timestamp": "2026-06-10T21:00:00+00:00",
        "source": "daily_close",
        "freshness_status": "live",
    }
    quote = _map_price_snapshot_to_quote(snap, _INSTRUMENT_UUID)
    assert quote["previous_close"] == pytest.approx(290.55)


def test_map_price_snapshot_to_quote_previous_close_null_when_change_unknown() -> None:
    """No price_change (single-session instrument) → previous_close=None, not price."""
    from api_gateway.routes.market import _map_price_snapshot_to_quote

    snap = {
        "instrument_id": _INSTRUMENT_UUID,
        "symbol": "NEWIPO",
        "price": "42.00",
        "price_change": None,
        "price_change_pct": None,
        "timestamp": "2026-06-10T14:00:00+00:00",
        "source": "fresh_quote",
        "freshness_status": "live",
    }
    quote = _map_price_snapshot_to_quote(snap, _INSTRUMENT_UUID)
    assert quote["previous_close"] is None
    # change/change_pct retain their legacy 0.0 coercion for old consumers.
    assert quote["change"] == 0.0


@pytest.mark.parametrize("section", ["income-statement", "balance-sheet", "cash-flow"])
@pytest.mark.asyncio
async def test_statement_proxies_forward_period_type_param(authed_app, authed_mock_clients, section) -> None:
    """Backend-gaps wave 3: ?period_type=annual must reach S3 (was dropped)."""
    s3_body = json.dumps({"security_id": _INSTRUMENT_UUID, "records": []}).encode()
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_http_response(200, s3_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{_INSTRUMENT_UUID}/{section}?period_type=annual",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args.kwargs
    assert call_kwargs.get("params") == {"period_type": "annual"}
