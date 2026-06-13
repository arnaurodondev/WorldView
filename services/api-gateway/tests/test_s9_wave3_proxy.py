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
    """GET /v1/market/heatmap returns 11 GICS sectors.

    After BP-fix 2026-05-11 the heatmap uses a single GET /sector-returns call
    (not 11 parallel screener POSTs) — mock market_data.get instead of .post.
    """
    _all_sectors = [
        "Energy",
        "Materials",
        "Industrials",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Financials",
        "Information Technology",
        "Communication Services",
        "Utilities",
        "Real Estate",
    ]
    sector_returns_resp = _mock_response(
        200,
        json.dumps(
            {
                "sectors": [
                    {
                        "name": name,
                        "change_pct": 1.5 if name == "Energy" else 0.5,
                        "instrument_count": 1,
                    }
                    for name in _all_sectors
                ]
            }
        ).encode(),
    )
    authed_mock_clients.market_data.get = AsyncMock(return_value=sector_returns_resp)

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
    energy_sector = next(s for s in body["sectors"] if s["name"] == "Energy")
    assert energy_sector["change_pct"] == 1.5


@pytest.mark.asyncio
async def test_heatmap_handles_partial_failure(authed_app, authed_mock_clients) -> None:
    """Heatmap propagates upstream error when sector-returns fails.

    After BP-fix 2026-05-11 the heatmap delegates to a single GET /sector-returns
    endpoint. When that endpoint returns 5xx, there is no partial-success path;
    the heatmap returns the upstream status code to the caller.
    """
    error_resp = _mock_response(500, b'{"detail": "Internal Server Error"}')
    authed_mock_clients.market_data.get = AsyncMock(return_value=error_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # DownstreamError → HTTPException with the upstream status code.
    assert resp.status_code == 500


# ── Top movers ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_movers_gainers_desc(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?type=gainers calls S3 period-movers via GET with type=gainers."""
    # Implementation uses clients.market_data.get() — NOT .post() — forwarding
    # period/type/limit as URL query params in the path string (not a POST body).
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps({"results": [], "type": "gainers", "period": "1D"}).encode(),
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers", "limit": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    # The implementation passes params in the URL path string, not as a params kwarg.
    call_args = authed_mock_clients.market_data.get.call_args[0]
    url = call_args[0]  # First positional arg is the URL string
    assert "type=gainers" in url
    assert "limit=5" in url


@pytest.mark.asyncio
async def test_top_movers_losers_asc(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?type=losers calls S3 period-movers via GET with type=losers."""
    # Implementation uses clients.market_data.get() — NOT .post() — with type=losers
    # embedded in the URL query string.
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps({"results": [], "type": "losers", "period": "1D"}).encode(),
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "losers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args[0]
    url = call_args[0]
    assert "type=losers" in url


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
    # BP-340 fix (PLAN-0068): EventType.MACRO = "macro"; economic events are stored as "macro",
    # not "economic". Using "economic" matched no rows and silently returned an empty list.
    assert call_kwargs["params"]["event_type"] == "macro"


# ── AI signals proxy (PLAN-0029: stub replaced with real S6 proxy) ──���────────


@pytest.mark.asyncio
async def test_ai_signals_proxy_to_s6(authed_app, authed_mock_clients) -> None:
    """GET /v1/signals/ai proxies S6 /news/trending-entities → NEWS MOMENTUM rows.

    PLAN-0099 W4: the feed is now per-entity momentum (ticker + trend + headline),
    proxied verbatim from S6's trending-entities endpoint, under the ``signals`` key.
    """
    s6_payload = {
        "entities": [
            {
                "entity_id": "ccc-ddd",
                "ticker": "NVDA",
                "name": "Nvidia",
                "count": 6,
                "prior_count": 2,
                "delta": 4,
                "delta_pct": 200.0,
                "top_article": {
                    "id": "art-1",
                    "title": "Nvidia surges on earnings",
                    "url": "https://finance.yahoo.com/x",
                    "source": "yahoo",
                    "published_at": "2026-06-11T22:00:00Z",
                    "sentiment": "positive",
                    "relevance": 0.81,
                },
            }
        ],
        "window_hours": 24,
    }
    import json as _json

    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, _json.dumps(s6_payload).encode()),
    )
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/ai",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "signals" in body
    assert len(body["signals"]) == 1
    sig = body["signals"][0]
    assert sig["entity_id"] == "ccc-ddd"
    assert sig["ticker"] == "NVDA"
    assert sig["delta_pct"] == 200.0
    assert sig["top_article"]["title"] == "Nvidia surges on earnings"
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
    """Heatmap passes through mixed null/non-null sector data from sector-returns.

    After BP-fix 2026-05-11 the heatmap uses a single GET /sector-returns response.
    Sectors with no trading data return null change_pct; sectors with data return
    a float. Verifies the passthrough preserves both variants correctly.
    """
    _all_sectors = [
        "Energy",
        "Materials",
        "Industrials",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Financials",
        "Information Technology",
        "Communication Services",
        "Utilities",
        "Real Estate",
    ]
    # First 5 sectors have data; remaining 6 have null change_pct (no trading activity).
    sector_data = [{"name": name, "change_pct": 1.5, "instrument_count": 1} for name in _all_sectors[:5]] + [
        {"name": name, "change_pct": None, "instrument_count": 0} for name in _all_sectors[5:]
    ]
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps({"sectors": sector_data}).encode())
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sectors"]) == 11
    # First 5 sectors have data → non-null change_pct
    for sector in body["sectors"][:5]:
        assert sector["change_pct"] == 1.5
    # Remaining 6 sectors have no data → null change_pct
    for sector in body["sectors"][5:]:
        assert sector["change_pct"] is None


@pytest.mark.asyncio
async def test_top_movers_downstream_500(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers when S3 period-movers returns 500 → DownstreamError → 500.

    get_top_movers() uses clients.market_data.get() (not .post()); it raises
    DownstreamError on failure, which the route handler converts to HTTPException.
    """
    error_resp = _mock_response(500, b'{"detail": "Internal Server Error"}')
    error_resp.text = '{"detail": "Internal Server Error"}'
    # Mock .get not .post — the implementation calls market_data.get()
    authed_mock_clients.market_data.get = AsyncMock(return_value=error_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_top_movers_downstream_read_timeout_returns_504(authed_app, authed_mock_clients) -> None:
    """Cold-start regression (Open issue #3): httpx.ReadTimeout on market-data
    must be wrapped into DownstreamError(504), NOT propagate as a raw 500.

    Pre-fix: client raised httpx.ReadTimeout, route handler only caught
    DownstreamError → FastAPI defaulted to 500. Post-fix: clients.market.get_top_movers
    catches the timeout and re-raises DownstreamError(status=504), which the
    handler maps to HTTPException(504, "Gateway Timeout").
    """
    # AsyncMock side_effect raises when awaited — simulates downstream timeout.
    authed_mock_clients.market_data.get = AsyncMock(side_effect=httpx.ReadTimeout("simulated cold start"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 504
    body = resp.json()
    # Detail should mention the underlying timeout class so on-call can grep logs.
    assert "timeout" in body["detail"].lower()
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_top_movers_downstream_connect_timeout_returns_504(authed_app, authed_mock_clients) -> None:
    """Same as ReadTimeout case but for ConnectTimeout — both must yield 504."""
    authed_mock_clients.market_data.get = AsyncMock(side_effect=httpx.ConnectTimeout("simulated connect timeout"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 504
    authed_mock_clients.market_data.get.assert_called_once()


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


# ── PLAN-0043 B-4: Period param on heatmap + movers ─────────────────────────


@pytest.mark.asyncio
async def test_heatmap_period_1w_routes_to_s3_ohlcv(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/heatmap?period=1W calls S3 OHLCV aggregate (GET), not screener (POST)."""
    # S3 sector-returns endpoint returns the pre-aggregated structure
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps({"sectors": [{"name": "Technology", "change_pct": 2.5, "instrument_count": 5}]}).encode(),
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            params={"period": "1W"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Response from S3 passed through; should include the sectors array
    assert "sectors" in body
    # Verify it called GET (sector-returns), not POST (screener)
    authed_mock_clients.market_data.get.assert_called_once()
    # Should NOT have called the screener POST endpoint
    authed_mock_clients.market_data.post.assert_not_called()


@pytest.mark.asyncio
async def test_heatmap_period_invalid_returns_400(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/heatmap?period=2W → 400 bad request."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/heatmap",
            params={"period": "2W"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_top_movers_period_1m_routes_to_s3_ohlcv(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?period=1M calls S3 period-movers (GET), not screener (POST)."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps(
                {
                    "results": [{"instrument_id": "i1", "ticker": "AAPL", "name": "Apple", "period_return_pct": 5.2}],
                    "type": "gainers",
                    "period": "1M",
                }
            ).encode(),
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers", "period": "1M"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # Verify it called GET (period-movers), not POST (screener)
    authed_mock_clients.market_data.get.assert_called_once()
    authed_mock_clients.market_data.post.assert_not_called()


@pytest.mark.asyncio
async def test_top_movers_period_invalid_returns_400(authed_app, authed_mock_clients) -> None:
    """GET /v1/market/top-movers?period=3M → 400 bad request."""
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/market/top-movers",
            params={"type": "gainers", "period": "3M"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 400


# ── Fundamentals snapshot proxy (PLAN-0050 Wave D T-D-4-04) ──────────────────


@pytest.mark.asyncio
async def test_fundamentals_snapshot_requires_auth(app, mock_clients) -> None:
    """GET /v1/fundamentals/{id}/snapshot without auth → 401.

    WHY UUID: instrument_id is now UUID-typed (F-010 security fix); non-UUID → 422.
    """
    # WHY UUID: F-010 — must use valid UUID so FastAPI doesn't short-circuit with 422.
    valid_id = "11111111-1111-1111-1111-111111111111"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/fundamentals/{valid_id}/snapshot")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_fundamentals_snapshot_proxies_to_s3(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/snapshot → S3 /api/v1/fundamentals/{id}/snapshot.

    WHY: The snapshot endpoint returns the 10 pre-computed derived metrics from
    the instrument_fundamentals_snapshot table.  S9 proxies it without transformation.
    The endpoint must return 200 even when all fields are null (instrument not yet
    backfilled) — never 404.
    """
    # WHY UUID: F-010 — instrument_id is now UUID-typed; non-UUID values → 422.
    aapl_id = "11111111-1111-1111-1111-111111111111"
    snapshot_payload = {
        "instrument_id": aapl_id,
        "eps_ttm": 6.11,
        "beta": 1.29,
        "avg_volume_30d": 56000000,
        "operating_cash_flow": 110543000000.0,
        "capex": 11455000000.0,
        "free_cash_flow": 99088000000.0,
        "fcf_margin": 0.2513,
        "interest_coverage": 30.37,
        "net_debt_to_ebitda": 0.77,
        "credit_rating": None,
        "updated_at": "2026-04-29T02:00:00Z",
    }
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(snapshot_payload).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{aapl_id}/snapshot",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == aapl_id
    assert body["eps_ttm"] == pytest.approx(6.11)
    assert body["beta"] == pytest.approx(1.29)
    assert body["avg_volume_30d"] == 56_000_000
    assert body["free_cash_flow"] == pytest.approx(99_088_000_000.0)
    assert body["credit_rating"] is None
    # Verify S3 was called with the correct path
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args
    assert "snapshot" in call_args[0][0]  # path contains "snapshot"


@pytest.mark.asyncio
async def test_fundamentals_snapshot_all_null_fields(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/snapshot returns 200 with all-null fields when
    no snapshot exists.  Frontend renders '—' for nulls — never a 404 error.

    WHY test this: instruments that have never been through the backfill (e.g.
    newly-listed stocks, ETFs with no cash flow statements) will have the endpoint
    return a valid 200 with all null fields.  This is the expected behaviour as per
    the API design in T-D-4-04 and the S3 /snapshot implementation.
    """
    # WHY UUID: F-010 — instrument_id is now UUID-typed; non-UUID values → 422.
    etf_id = "22222222-2222-2222-2222-222222222222"
    all_null_payload = {
        "instrument_id": etf_id,
        "eps_ttm": None,
        "beta": None,
        "avg_volume_30d": None,
        "operating_cash_flow": None,
        "capex": None,
        "free_cash_flow": None,
        "fcf_margin": None,
        "interest_coverage": None,
        "net_debt_to_ebitda": None,
        "credit_rating": None,
        "updated_at": None,
    }
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(all_null_payload).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{etf_id}/snapshot",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == etf_id
    # All derived metric fields null
    for field in ("eps_ttm", "beta", "avg_volume_30d", "free_cash_flow", "credit_rating"):
        assert body[field] is None, f"Expected {field} to be null"


@pytest.mark.asyncio
async def test_fundamentals_snapshot_downstream_error_forwarded(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}/snapshot when S3 returns 500 → 500 forwarded to client."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
    )
    # WHY UUID: F-010 — instrument_id is now UUID-typed; non-UUID values → 422.
    valid_id = "11111111-1111-1111-1111-111111111111"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{valid_id}/snapshot",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
