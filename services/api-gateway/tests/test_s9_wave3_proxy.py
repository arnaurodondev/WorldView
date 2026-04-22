"""Tests for PRD-0028 Wave S9-3 composed endpoints (search, heatmap, top-movers,
economic calendar, AI signals stub).

Uses the shared conftest fixtures:
- ``app`` / ``mock_clients`` for unauthenticated/public routes
- ``authed_app`` / ``authed_mock_clients`` for authenticated route tests
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
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
    resp.text = content.decode()
    resp.json.return_value = json.loads(content)
    return resp


def _inject_rsa_keys(application) -> None:
    """Inject real RSA keys into app state so _system_headers() can issue JWTs."""
    from api_gateway.oidc import rsa_key_id

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    application.state.rsa_private_key = private_key
    application.state.rsa_public_key = private_key.public_key()
    application.state.rsa_kid = rsa_key_id(private_key.public_key())


# ── Search instruments ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_instruments_no_auth(app, mock_clients) -> None:
    """GET /v1/search/instruments should work without authentication."""
    mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [], "total": 0}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/search/instruments", params={"q": "apple", "limit": "5"})

    assert resp.status_code == 200
    mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_search_instruments_q_param(app, mock_clients) -> None:
    """GET /v1/search/instruments?q=AAPL forwards q as 'query' param to S3."""
    mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [], "total": 0}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/search/instruments", params={"q": "AAPL", "limit": "10"})

    assert resp.status_code == 200
    call_kwargs = mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"]["query"] == "AAPL"
    assert call_kwargs["params"]["limit"] == 10


# ── Market heatmap ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heatmap_requires_auth(app, mock_clients) -> None:
    """GET /v1/market/heatmap without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/market/heatmap")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_heatmap_returns_11_sectors(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/heatmap returns 11 GICS sectors."""
    sector_resp = _mock_response(
        200,
        json.dumps(
            {
                "results": [
                    {
                        "instrument_id": "i1",
                        "ticker": "XOM",
                        "name": "Exxon",
                        "exchange": "US",
                        "sector": "Energy",
                        "metrics": {"daily_return": 1.5},
                    },
                ],
                "count": 1,
                "total": 1,
            }
        ).encode(),
    )
    authed_mock_clients.market_data.post = AsyncMock(return_value=sector_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sectors"]) == 11
    assert body["sectors"][0]["name"] == "Energy"


@pytest.mark.asyncio
async def test_heatmap_handles_partial_failure(authed_app, authed_mock_clients) -> None:
    """Heatmap returns null change_pct for sectors where S3 fails."""
    error_resp = _mock_response(500, b'{"detail": "Internal Server Error"}')
    authed_mock_clients.market_data.post = AsyncMock(return_value=error_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # All sectors should have null change_pct due to S3 failure
    assert all(s["change_pct"] is None for s in body["sectors"])


# ── Top movers ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_movers_gainers_desc(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?type=gainers calls S3 with sort_order=desc."""
    authed_mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(200, b'{"results": [], "count": 0, "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers", "limit": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.post.assert_called_once()
    call_kwargs = authed_mock_clients.market_data.post.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["sort_order"] == "desc"
    assert body["limit"] == 5


@pytest.mark.asyncio
async def test_top_movers_losers_asc(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?type=losers calls S3 with sort_order=asc."""
    authed_mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(200, b'{"results": [], "count": 0, "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "losers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.post.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["sort_order"] == "asc"


@pytest.mark.asyncio
async def test_top_movers_requires_auth(app, mock_clients) -> None:
    """GET /v1/market/top-movers without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/market/top-movers")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_top_movers_invalid_type(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?type=invalid → 400."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "invalid"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 400


# ── Economic calendar ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_economic_calendar_requires_auth(app, mock_clients) -> None:
    """GET /v1/fundamentals/economic-calendar without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/fundamentals/economic-calendar")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_economic_calendar_proxies_to_s7(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/economic-calendar proxies to S7 temporal-events."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"events": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/economic-calendar",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    # R-002 fix: S7 expects `event_type`, not `type` — assertion updated from "type" to "event_type"
    assert call_kwargs["params"]["event_type"] == "economic"


# ── AI signals proxy (PLAN-0029: stub replaced with real S6 proxy) ──���────────


@pytest.mark.asyncio
async def test_ai_signals_proxy_to_s6(authed_app, authed_mock_clients) -> None:
    """GET /v1/signals/ai proxies to S6 NLP Pipeline (no longer a stub)."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"signals": [{"id": "s1"}], "total": 1}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/ai",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["signals"] == [{"id": "s1"}]
    assert body["total"] == 1
    authed_mock_clients.nlp_pipeline.get.assert_called_once()


@pytest.mark.asyncio
async def test_ai_signals_requires_auth(app, mock_clients) -> None:
    """GET /v1/signals/ai without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/ai")

    assert resp.status_code == 401


# ── Watchlist rename proxy (PLAN-0029) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_watchlist_proxy_requires_auth(app, mock_clients) -> None:
    """PATCH /v1/watchlists/{id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch("/v1/watchlists/wl-1", json={"name": "X"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_patch_watchlist_proxy_forwards_body(authed_app, authed_mock_clients) -> None:
    """PATCH /v1/watchlists/{id} forwards body to S1 with portfolio headers."""
    authed_mock_clients.portfolio.patch = AsyncMock(
        return_value=_mock_response(200, b'{"id": "wl-1", "name": "Renamed"}'),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            "/v1/watchlists/wl-1",
            json={"name": "Renamed"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    authed_mock_clients.portfolio.patch.assert_called_once()


# ── F-002: Downstream error handling ────────────────────────────────────────


@pytest.mark.asyncio
async def test_heatmap_mixed_success_failure(authed_app, authed_mock_clients) -> None:
    """Heatmap with some sectors succeeding and others failing.

    First 5 sector screener calls return valid data; remaining 6 return 500.
    Successful sectors should have a computed change_pct; failed sectors should
    have null change_pct.
    """
    success_resp = _mock_response(
        200,
        json.dumps(
            {
                "results": [
                    {
                        "instrument_id": "i1",
                        "ticker": "XOM",
                        "name": "Exxon",
                        "exchange": "US",
                        "sector": "Energy",
                        "metrics": {"daily_return": 1.5},
                    },
                ],
                "count": 1,
                "total": 1,
            }
        ).encode(),
    )
    error_resp = _mock_response(500, b'{"detail": "Internal Server Error"}')
    # First 5 calls succeed, remaining 6 fail
    responses = [success_resp] * 5 + [error_resp] * 6
    authed_mock_clients.market_data.post = AsyncMock(side_effect=responses)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sectors"]) == 11
    # First 5 sectors should have a non-null change_pct (1.5 average)
    for sector in body["sectors"][:5]:
        assert sector["change_pct"] is not None
        assert sector["change_pct"] == 1.5
    # Remaining 6 sectors should have null change_pct due to 500 errors
    for sector in body["sectors"][5:]:
        assert sector["change_pct"] is None


@pytest.mark.asyncio
async def test_top_movers_downstream_500(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers when S3 screener returns 500 → DownstreamError → 500.

    get_top_movers() raises DownstreamError on failure, which the route handler
    converts to an HTTPException with the same status code.
    """
    error_resp = _mock_response(500, b'{"detail": "Internal Server Error"}')
    error_resp.text = '{"detail": "Internal Server Error"}'
    authed_mock_clients.market_data.post = AsyncMock(return_value=error_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
    authed_mock_clients.market_data.post.assert_called_once()


@pytest.mark.asyncio
async def test_economic_calendar_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/economic-calendar when S7 returns 503 → 503 forwarded."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/economic-calendar",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    authed_mock_clients.knowledge_graph.get.assert_called_once()


@pytest.mark.asyncio
async def test_search_instruments_downstream_error(app, mock_clients) -> None:
    """GET /v1/search/instruments when S3 returns 500 → 500 forwarded.

    Search is a public endpoint (no auth required), so the 500 from S3 is
    forwarded transparently to the caller.
    """
    mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/search/instruments", params={"q": "apple"})

    assert resp.status_code == 500
    mock_clients.market_data.get.assert_called_once()


# ── F-02: Search instruments sends system JWT ─────────────────────────────────


@pytest.mark.asyncio
async def test_search_instruments_sends_system_jwt(app, mock_clients) -> None:
    """F-02: GET /v1/search/instruments (public) sends X-Internal-JWT to S3."""
    _inject_rsa_keys(app)
    mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [], "total": 0}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/search/instruments", params={"q": "AAPL"})

    assert resp.status_code == 200
    call_kwargs = mock_clients.market_data.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})
