"""Tests for PRD-0028 Wave S9-2 proxy routes (Portfolio, Holdings, Transactions,
Watchlists, Auth Register, WS-Token).

Uses the shared conftest fixtures:
- ``app`` / ``mock_clients`` for unauthenticated routes and 401 tests
- ``authed_app`` / ``authed_mock_clients`` for authenticated route tests
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
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
    return resp


# ── Portfolio ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolios_proxy_requires_auth(app, mock_clients) -> None:
    """GET /v1/portfolios without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios")

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_portfolios_proxy_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/portfolios with valid JWT → 200 proxied from S1."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"portfolios": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.portfolio.get.assert_called_once()
    call_args = authed_mock_clients.portfolio.get.call_args[0]
    assert "/api/v1/portfolios" in call_args[0]


@pytest.mark.asyncio
async def test_portfolios_proxy_no_legacy_headers(authed_app, authed_mock_clients) -> None:
    """F-MAJOR-013: GET /v1/portfolios does NOT send legacy X-Owner-ID / X-User-Id / X-Tenant-Id.

    S1 now reads tenant_id/user_id from the X-Internal-JWT payload via InternalJWTMiddleware.
    Only X-Internal-JWT is forwarded by _portfolio_headers().
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"portfolios": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.portfolio.get.call_args[1]
    headers_sent = call_kwargs["headers"]
    # Legacy headers must NOT be present (F-MAJOR-013)
    assert "X-Owner-ID" not in headers_sent
    assert "X-User-Id" not in headers_sent
    assert "X-Tenant-Id" not in headers_sent


# ── Holdings ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_holdings_proxy_requires_auth(app, mock_clients) -> None:
    """GET /v1/holdings/{id} without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/holdings/portfolio-1")

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_holdings_proxy_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/holdings/{id} with valid JWT → 200 proxied from S1."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"holdings": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/holdings/portfolio-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.portfolio.get.call_args[0]
    assert "/api/v1/holdings/portfolio-1" in call_args[0]


# ── Transactions ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transactions_get_forwards_portfolio_id_as_header(authed_app, authed_mock_clients) -> None:
    """GET /v1/transactions?portfolio_id=x forwards portfolio_id as X-Portfolio-ID header.

    API-004 fix: S1 expects portfolio_id as the X-Portfolio-ID header, not as a
    query parameter.  The proxy must extract it from query params and inject it
    as a header so S1 can validate portfolio ownership.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"transactions": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/transactions",
            params={"portfolio_id": "p-1", "limit": "10", "offset": "0"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.portfolio.get.call_args[1]
    # portfolio_id must be in the headers, NOT in query params
    forwarded_headers = call_kwargs.get("headers", {})
    assert (
        forwarded_headers.get("X-Portfolio-ID") == "p-1"
    ), "portfolio_id must be forwarded as X-Portfolio-ID header (API-004)"
    assert "portfolio_id" not in call_kwargs.get(
        "params", {}
    ), "portfolio_id must not remain in query params after extraction"
    # Other query params are still forwarded as params
    assert call_kwargs["params"].get("limit") == "10"
    assert call_kwargs["params"].get("offset") == "0"


@pytest.mark.asyncio
async def test_transactions_get_without_portfolio_id_still_proxies(authed_app, authed_mock_clients) -> None:
    """GET /v1/transactions without portfolio_id still proxies (S1 validates ownership).

    When portfolio_id is absent, the request is forwarded without X-Portfolio-ID —
    S1 will return 422 but the proxy should not crash.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(422, b'{"detail": "X-Portfolio-ID required"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/transactions",
            params={"limit": "10"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # S1 returns 422 — proxy forwards it without crashing
    assert resp.status_code == 422
    call_kwargs = authed_mock_clients.portfolio.get.call_args[1]
    # No X-Portfolio-ID header when portfolio_id was absent
    assert "X-Portfolio-ID" not in call_kwargs.get("headers", {})


@pytest.mark.asyncio
async def test_transactions_post_body_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/transactions forwards request body to S1."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(201, b'{"transaction_id": "tx-1"}'),
    )

    body = b'{"portfolio_id": "p-1", "symbol": "AAPL", "side": "buy", "quantity": 10}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/transactions",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201
    authed_mock_clients.portfolio.post.assert_called_once()
    call_kwargs = authed_mock_clients.portfolio.post.call_args[1]
    assert call_kwargs["content"] == body


# ── Watchlists ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watchlists_list_requires_auth(app, mock_clients) -> None:
    """GET /v1/watchlists without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/watchlists")

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_watchlist_create_body_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/watchlists forwards request body to S1."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(201, b'{"watchlist_id": "wl-1"}'),
    )

    body = b'{"name": "Tech Stocks"}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/watchlists",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201
    authed_mock_clients.portfolio.post.assert_called_once()
    call_kwargs = authed_mock_clients.portfolio.post.call_args[1]
    assert call_kwargs["content"] == body


@pytest.mark.asyncio
async def test_watchlist_get_single(authed_app, authed_mock_clients) -> None:
    """GET /v1/watchlists/{id} proxied to S1."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"watchlist_id": "wl-1", "name": "Tech"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.portfolio.get.call_args[0]
    assert "/api/v1/watchlists/wl-1" in call_args[0]


@pytest.mark.asyncio
async def test_watchlist_delete_returns_200(authed_app, authed_mock_clients) -> None:
    """DELETE /v1/watchlists/{id} returns 200 (not 204, BP-064)."""
    authed_mock_clients.portfolio.delete = AsyncMock(
        return_value=_mock_response(200, b'{"deleted": true}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/v1/watchlists/wl-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.portfolio.delete.assert_called_once()
    call_args = authed_mock_clients.portfolio.delete.call_args[0]
    assert "/api/v1/watchlists/wl-1" in call_args[0]


@pytest.mark.asyncio
async def test_watchlist_members_list_requires_auth(app, mock_clients) -> None:
    """GET /v1/watchlists/{id}/members without auth → 401 (PLAN-0046 / T-46-2-02)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/watchlists/wl-1/members")

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_watchlist_members_list_proxies_to_s1(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/watchlists/{id}/members proxied to S1 with pagination preserved.

    PLAN-0046 / BP-265 — the gateway must actually fetch members rather than
    silently returning an empty array.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(
            200,
            b'{"members": [{"entity_id": "e-1", "entity_type": "company",'
            b' "ticker": "AAPL", "name": "Apple Inc.",'
            b' "instrument_id": "i-1", "added_at": "2026-01-01T00:00:00Z"}],'
            b' "total": 1}',
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists/wl-1/members?limit=50&offset=10",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.portfolio.get.assert_called_once()
    call_args = authed_mock_clients.portfolio.get.call_args[0]
    # Verify the path and that the query string was forwarded verbatim.
    assert "/api/v1/watchlists/wl-1/members" in call_args[0]
    assert "limit=50" in call_args[0]
    assert "offset=10" in call_args[0]


@pytest.mark.asyncio
async def test_watchlist_member_add(authed_app, authed_mock_clients) -> None:
    """POST /v1/watchlists/{id}/members forwards body to S1."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(201, b'{"member_id": "m-1"}'),
    )

    body = b'{"entity_id": "ent-1"}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/watchlists/wl-1/members",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201
    authed_mock_clients.portfolio.post.assert_called_once()
    call_args = authed_mock_clients.portfolio.post.call_args[0]
    assert "/api/v1/watchlists/wl-1/members" in call_args[0]
    call_kwargs = authed_mock_clients.portfolio.post.call_args[1]
    assert call_kwargs["content"] == body


@pytest.mark.asyncio
async def test_watchlist_member_delete(authed_app, authed_mock_clients) -> None:
    """DELETE /v1/watchlists/{wid}/members/{eid} proxied with correct path."""
    authed_mock_clients.portfolio.delete = AsyncMock(
        return_value=_mock_response(200, b'{"deleted": true}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/v1/watchlists/wl-1/members/ent-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.portfolio.delete.assert_called_once()
    call_args = authed_mock_clients.portfolio.delete.call_args[0]
    assert "/api/v1/watchlists/wl-1/members/ent-1" in call_args[0]


# ── Auth Register ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_redirect_302(app) -> None:
    """GET /v1/auth/register → 302 redirect to Zitadel registration page."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        resp = await client.get("/v1/auth/register")

    assert resp.status_code == 302
    location = resp.headers.get("location", "")
    assert "example.zitadel.cloud" in location
    assert "/ui/console/register" in location


# ── F-002: Downstream error handling ────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolios_downstream_500(authed_app, authed_mock_clients) -> None:
    """GET /v1/portfolios when S1 returns 500 → sanitized 502, no upstream body leak (BUG-7)."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "psql ERROR: relation users does not exist"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 502
    assert b"psql" not in resp.content
    assert b"relation users" not in resp.content
    assert resp.json() == {"detail": "upstream service error"}
    authed_mock_clients.portfolio.get.assert_called_once()


@pytest.mark.asyncio
async def test_watchlist_create_downstream_error(authed_app, authed_mock_clients) -> None:
    """POST /v1/watchlists when S1 returns 503 → 503 forwarded transparently."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    body = b'{"name": "Tech Stocks"}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/watchlists",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 503
    authed_mock_clients.portfolio.post.assert_called_once()


@pytest.mark.asyncio
async def test_transactions_post_downstream_error(authed_app, authed_mock_clients) -> None:
    """POST /v1/transactions when S1 returns 500 → sanitized 502, no upstream body leak (BUG-7)."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Traceback (most recent call last): File app.py"}'),
    )

    body = b'{"portfolio_id": "p-1", "symbol": "AAPL", "side": "buy", "quantity": 10}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/transactions",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 502
    assert b"Traceback" not in resp.content
    assert resp.json() == {"detail": "upstream service error"}
    authed_mock_clients.portfolio.post.assert_called_once()


# ── F-MAJOR-013: No legacy header assertions ──────────────────────────────────


@pytest.mark.asyncio
async def test_holdings_proxy_no_legacy_headers(authed_app, authed_mock_clients) -> None:
    """F-MAJOR-013: GET /v1/holdings/{id} does NOT send legacy X-Owner-ID / X-User-Id.

    S1 now reads user_id from the X-Internal-JWT payload via InternalJWTMiddleware.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"holdings": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/holdings/portfolio-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.portfolio.get.call_args[1]
    headers_sent = call_kwargs["headers"]
    assert "X-Owner-ID" not in headers_sent
    assert "X-User-Id" not in headers_sent


@pytest.mark.asyncio
async def test_watchlists_list_no_legacy_headers(authed_app, authed_mock_clients) -> None:
    """F-MAJOR-013: GET /v1/watchlists does NOT send legacy X-Owner-ID / X-User-Id.

    S1 now reads user_id from the X-Internal-JWT payload via InternalJWTMiddleware.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"watchlists": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/watchlists",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.portfolio.get.call_args[1]
    headers_sent = call_kwargs["headers"]
    assert "X-Owner-ID" not in headers_sent
    assert "X-User-Id" not in headers_sent


# ── Force-sync proxy (brokerage) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_brokerage_sync_requires_auth(app, mock_clients) -> None:
    """POST /v1/brokerage-connections/{id}/sync without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/brokerage-connections/conn-1/sync")

    assert resp.status_code == 401
    mock_clients.portfolio.post.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_brokerage_sync_proxied_202(authed_app, authed_mock_clients) -> None:
    """POST /v1/brokerage-connections/{id}/sync with valid JWT → 202 proxied from S1."""
    conn_id = "fc3e8a42-0000-7000-8000-000000000001"
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(202, b'{"status": "syncing", "connection_id": "' + conn_id.encode() + b'"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/brokerage-connections/{conn_id}/sync",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 202
    authed_mock_clients.portfolio.post.assert_called_once()
    call_args = authed_mock_clients.portfolio.post.call_args[0]
    assert f"/api/v1/brokerage-connections/{conn_id}/sync" in call_args[0]


@pytest.mark.asyncio
async def test_trigger_brokerage_sync_forwards_s1_error(authed_app, authed_mock_clients) -> None:
    """POST /v1/brokerage-connections/{id}/sync forwards S1 error status codes transparently.

    If S1 returns 404 (connection not found) or 422 (not active), the proxy
    must forward the status code unchanged — no swallowing or re-mapping.
    """
    conn_id = "fc3e8a42-0000-7000-8000-000000000002"
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "Brokerage connection not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/brokerage-connections/{conn_id}/sync",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
    authed_mock_clients.portfolio.post.assert_called_once()
