"""Tests for prediction market proxy routes (PRD-0019 Wave C-1)."""

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


@pytest.mark.asyncio
async def test_list_proxy_forwards_query_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/signals/prediction-markets forwards ?status=open to S3."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"markets": [], "total": 0}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets",
            params={"status": "open"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("status") == "open"


@pytest.mark.asyncio
async def test_detail_proxy_404_passthrough(authed_app, authed_mock_clients) -> None:
    """S3 404 (unknown market) is propagated unchanged to the frontend."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(404, b'{"detail": "Market not found"}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/unknown-market",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_history_proxy_forwards_date_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/signals/prediction-markets/{id}/history forwards from/to/limit params."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"snapshots": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/market-1/history",
            params={"from": "2026-01-01", "to": "2026-04-09", "limit": "10"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    params = call_kwargs["params"]
    assert "from" in params
    assert "to" in params
    assert "limit" in params


@pytest.mark.asyncio
async def test_jwt_required(app, mock_clients) -> None:
    """Missing JWT → 401 Unauthorized; downstream S3 is never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/prediction-markets")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()
