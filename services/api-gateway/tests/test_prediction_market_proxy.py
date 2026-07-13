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


@pytest.mark.asyncio
async def test_list_proxy_forwards_category_param(authed_app, authed_mock_clients) -> None:
    """PLAN-0049 T-C-3-03: ``?category=politics`` is forwarded verbatim to S3."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"items": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets",
            params={"status": "open", "category": "politics"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    # Both params must reach the upstream — gateway must not strip either.
    assert call_kwargs["params"].get("category") == "politics"
    assert call_kwargs["params"].get("status") == "open"


@pytest.mark.asyncio
async def test_list_proxy_omits_category_when_absent(authed_app, authed_mock_clients) -> None:
    """No category param → upstream ``params`` dict has no ``category`` key.

    Guards against a regression where the explicit FastAPI param signature
    might inject ``category=None`` into the forwarded dict and confuse the
    upstream's NULL-vs-absent semantics.
    """
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(200, b'{"items": []}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets",
            params={"status": "open"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert "category" not in call_kwargs["params"]


# ── PLAN-0056 Wave E1: events / trades / entity-predictions ──────────────────


@pytest.mark.asyncio
async def test_events_list_proxy_forwards_pagination(authed_app, authed_mock_clients) -> None:
    """GET /v1/signals/prediction-markets/events forwards limit/offset to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [], "total": 0, "limit": 20, "offset": 0}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/events",
            params={"limit": "20", "offset": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # The literal "events" path must NOT be swallowed by the /{market_id} route.
    call_args = authed_mock_clients.market_data.get.call_args
    assert call_args[0][0] == "/api/v1/prediction-markets/events"
    params = call_args[1]["params"]
    assert params.get("limit") == "20"
    assert params.get("offset") == "5"


@pytest.mark.asyncio
async def test_events_list_requires_auth(app, mock_clients) -> None:
    """Missing JWT → 401; downstream S3 is never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/prediction-markets/events")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_event_detail_404_passthrough(authed_app, authed_mock_clients) -> None:
    """Unknown event_id → S3 404 propagated unchanged to the frontend."""
    authed_mock_clients.market_data.get = AsyncMock(return_value=_mock_response(404, b'{"detail": "Event not found"}'))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/events/evt-unknown",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
    # Must route to the event-detail S3 path, not the market-detail path.
    assert authed_mock_clients.market_data.get.call_args[0][0] == "/api/v1/prediction-markets/events/evt-unknown"


@pytest.mark.asyncio
async def test_trades_proxy_forwards_since_and_limit(authed_app, authed_mock_clients) -> None:
    """GET /{id}/trades forwards since/limit query params to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"market_id": "m-1", "items": [], "limit": 100}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/m-1/trades",
            params={"since": "2026-07-01T00:00:00Z", "limit": "50"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    assert call_args[0][0] == "/api/v1/prediction-markets/m-1/trades"
    params = call_args[1]["params"]
    assert "since" in params
    assert params.get("limit") == "50"


@pytest.mark.asyncio
async def test_history_forwards_interval_param(authed_app, authed_mock_clients) -> None:
    """PLAN-0056 A4: ``?interval=1d`` flows through the history proxy verbatim."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"market_id": "m-1", "points": []}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/signals/prediction-markets/m-1/history",
            params={"interval": "1d", "token_id": "tok-yes"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    params = authed_mock_clients.market_data.get.call_args[1]["params"]
    assert params.get("interval") == "1d"
    assert params.get("token_id") == "tok-yes"


# ── Entity predictions (T-E-1-02, proxies S7 knowledge-graph) ────────────────

_ENTITY_ID = "018f5a2b-1c3d-7e4f-8a9b-0c1d2e3f4a5b"


@pytest.mark.asyncio
async def test_entity_predictions_proxies_s7(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/predictions returns the S7 payload verbatim."""
    payload = (
        b'{"items": [{"condition_id": "0xabc", "question": "Will X happen?",'
        b' "polarity": "bullish", "polarity_confidence": 0.82,'
        b' "close_time": "2026-12-31T00:00:00Z", "confidence": 0.9}],'
        b' "total": 1, "limit": 50, "offset": 0}'
    )
    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=_mock_response(200, payload))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_ID}/predictions",
            params={"limit": "50", "offset": "0"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["condition_id"] == "0xabc"
    assert body["items"][0]["polarity"] == "bullish"
    # Proxies to S7 knowledge-graph (not S3 market-data): no odds hydration.
    call_args = authed_mock_clients.knowledge_graph.get.call_args
    assert call_args[0][0] == f"/api/v1/entities/{_ENTITY_ID}/predictions"
    assert call_args[1]["params"] == {"limit": 50, "offset": 0}


@pytest.mark.asyncio
async def test_entity_predictions_requires_auth(app, mock_clients) -> None:
    """Missing JWT → 401; S7 is never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{_ENTITY_ID}/predictions")

    assert resp.status_code == 401
    mock_clients.knowledge_graph.get.assert_not_called()


@pytest.mark.asyncio
async def test_entity_predictions_empty_list_not_404(authed_app, authed_mock_clients) -> None:
    """An entity with no linked markets → 200 with empty items (never 404)."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"items": [], "total": 0, "limit": 50, "offset": 0}')
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{_ENTITY_ID}/predictions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    assert resp.json()["items"] == []
