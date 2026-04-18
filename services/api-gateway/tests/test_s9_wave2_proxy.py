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
async def test_portfolios_proxy_owner_id_header(authed_app, authed_mock_clients) -> None:
    """GET /v1/portfolios sends X-Owner-ID (not X-User-Id) to S1.

    S1 expects X-Owner-ID — the _portfolio_headers() helper maps the
    X-User-Id from _auth_headers() to X-Owner-ID for all S1 calls.
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
    # X-Owner-ID must be present (S1 requirement)
    assert "X-Owner-ID" in headers_sent
    assert headers_sent["X-Owner-ID"] == "user-1"
    # X-User-Id must NOT be present (was remapped)
    assert "X-User-Id" not in headers_sent


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
async def test_transactions_get_forwards_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/transactions?portfolio_id=x&limit=10 forwards query params to S1."""
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
    assert call_kwargs["params"].get("portfolio_id") == "p-1"
    assert call_kwargs["params"].get("limit") == "10"


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
    """GET /v1/portfolios when S1 returns 500 → 500 forwarded transparently."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
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
    """POST /v1/transactions when S1 returns 500 → 500 forwarded transparently."""
    authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
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

    assert resp.status_code == 500
    authed_mock_clients.portfolio.post.assert_called_once()


# ── F-008: X-Owner-ID header assertions ─────────────────────────────────────


@pytest.mark.asyncio
async def test_holdings_proxy_owner_id_header(authed_app, authed_mock_clients) -> None:
    """GET /v1/holdings/{id} sends X-Owner-ID (not X-User-Id) to S1.

    The _portfolio_headers() helper remaps X-User-Id → X-Owner-ID for all
    S1 Portfolio calls.
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
    assert "X-Owner-ID" in headers_sent
    assert headers_sent["X-Owner-ID"] == "user-1"
    assert "X-User-Id" not in headers_sent


@pytest.mark.asyncio
async def test_watchlists_list_sends_owner_id_header(authed_app, authed_mock_clients) -> None:
    """GET /v1/watchlists sends X-Owner-ID (not X-User-Id) to S1.

    Verifies that the watchlists list endpoint also uses _portfolio_headers()
    to remap X-User-Id → X-Owner-ID.
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
    assert "X-Owner-ID" in headers_sent
    assert headers_sent["X-Owner-ID"] == "user-1"
    assert "X-User-Id" not in headers_sent
