"""Tests for PRD-0028 Wave S9-1 proxy routes (OHLCV, Quotes, Fundamentals,
Entity Graph, Contradictions, News, Briefings).

Uses the shared conftest fixtures:
- ``app`` / ``mock_clients`` for unauthenticated routes and 401 tests
- ``authed_app`` / ``authed_mock_clients`` for authenticated route tests
"""

from __future__ import annotations

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


# ── OHLCV ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohlcv_proxy_requires_auth(app, mock_clients) -> None:
    """GET /v1/ohlcv/{id} without auth → 401; downstream never called."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/ohlcv/instr-1")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_ohlcv_proxy_forwards_query_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id}?period=1d forwards query params to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"bars": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/ohlcv/instr-1",
            params={"period": "1d", "from": "2026-01-01"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("period") == "1d"
    assert call_kwargs["params"].get("from") == "2026-01-01"


@pytest.mark.asyncio
async def test_ohlcv_proxy_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id} with valid JWT → 200 proxied from S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"bars": [{"o": 100}]}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/ohlcv/instr-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert "/api/v1/ohlcv/instr-1" in call_args[0]


# ── Quotes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quotes_single_proxy(authed_app, authed_mock_clients) -> None:
    """GET /v1/quotes/{id} proxied correctly to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"price": 150.0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/quotes/instr-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert "/api/v1/quotes/instr-1" in call_args[0]


@pytest.mark.asyncio
async def test_quotes_batch_body_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/quotes/batch forwards request body to S3."""
    authed_mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(200, b'{"quotes": []}'),
    )

    body = b'{"instrument_ids": ["instr-1", "instr-2"]}'
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/quotes/batch",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.post.assert_called_once()
    call_kwargs = authed_mock_clients.market_data.post.call_args[1]
    assert call_kwargs["content"] == body


# ── Fundamentals ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fundamentals_proxy_unauthenticated(app, mock_clients) -> None:
    """GET /v1/fundamentals/{id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/fundamentals/instr-1")

    assert resp.status_code == 401
    mock_clients.market_data.get.assert_not_called()


@pytest.mark.asyncio
async def test_fundamentals_proxy_forwards_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/{id}?fields=pe_ratio forwards query params to S3."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"pe_ratio": 25.0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/instr-1",
            params={"fields": "pe_ratio"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("fields") == "pe_ratio"
    # Verify downstream path includes instrument_id
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert "/api/v1/fundamentals/instr-1" in call_args[0]


# ── Entity Graph + Contradictions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_graph_depth_param(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph?depth=2 forwards depth param to S7."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"nodes": [], "edges": []}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            params={"depth": "2"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    assert call_kwargs["params"].get("depth") == "2"
    call_args = authed_mock_clients.knowledge_graph.get.call_args[0]
    assert f"/api/v1/entities/{entity_id}/graph" in call_args[0]


@pytest.mark.asyncio
async def test_entity_contradictions_proxy(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/contradictions proxied to S7."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"contradictions": []}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000002"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/contradictions",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_args = authed_mock_clients.knowledge_graph.get.call_args[0]
    assert f"/api/v1/entities/{entity_id}/contradictions" in call_args[0]


# ── News ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_news_top_no_auth_required(app, mock_clients) -> None:
    """GET /v1/news/top works without authentication (public endpoint)."""
    mock_clients.content_store.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"hours": "24", "limit": "10"})

    assert resp.status_code == 200
    mock_clients.content_store.get.assert_called_once()
    call_kwargs = mock_clients.content_store.get.call_args[1]
    assert call_kwargs["params"].get("hours") == "24"
    assert call_kwargs["params"].get("limit") == "10"


@pytest.mark.asyncio
async def test_news_entity_requires_auth(app, mock_clients) -> None:
    """GET /v1/news/entity/{id} without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/news/entity/{entity_id}")

    assert resp.status_code == 401
    mock_clients.content_store.get.assert_not_called()


# ── Briefings ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_briefings_morning_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/morning without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/briefings/morning")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()


@pytest.mark.asyncio
async def test_briefings_morning_proxied(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning proxied to S8 rag-chat."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, b'{"briefing": "Good morning..."}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args[0]
    assert "/api/v1/briefings/morning" in call_args[0]


# ── F-002: Downstream error handling ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohlcv_proxy_downstream_500(authed_app, authed_mock_clients) -> None:
    """GET /v1/ohlcv/{id} when S3 returns 500 → 500 forwarded transparently."""
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(500, b'{"detail": "Internal Server Error"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/ohlcv/instr-1",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 500
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_entity_graph_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph when S7 returns 503 → 503 forwarded."""
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    authed_mock_clients.knowledge_graph.get.assert_called_once()


@pytest.mark.asyncio
async def test_news_top_downstream_error(app, mock_clients) -> None:
    """GET /v1/news/top when S5 returns 502 → 502 forwarded (public endpoint)."""
    mock_clients.content_store.get = AsyncMock(
        return_value=_mock_response(502, b'{"detail": "Bad Gateway"}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top")

    assert resp.status_code == 502
    mock_clients.content_store.get.assert_called_once()


@pytest.mark.asyncio
async def test_briefings_morning_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/morning when S8 returns 503 → 503 forwarded."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/briefings/morning",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    authed_mock_clients.rag_chat.get.assert_called_once()


# ── F-007: Briefings/instrument tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_briefings_instrument_requires_auth(app, mock_clients) -> None:
    """GET /v1/briefings/instrument/{id} without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/briefings/instrument/{entity_id}")

    assert resp.status_code == 401
    mock_clients.rag_chat.get.assert_not_called()


@pytest.mark.asyncio
async def test_briefings_instrument_proxied(authed_app, authed_mock_clients) -> None:
    """GET /v1/briefings/instrument/{id} with auth → proxied to S8."""
    authed_mock_clients.rag_chat.get = AsyncMock(
        return_value=_mock_response(200, b'{"briefing": "AAPL analysis..."}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/briefings/instrument/{entity_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.rag_chat.get.assert_called_once()
    call_args = authed_mock_clients.rag_chat.get.call_args[0]
    assert f"/api/v1/briefings/instrument/{entity_id}" in call_args[0]


# ── F-013: News/entity authenticated test ───────────────────────────────────


@pytest.mark.asyncio
async def test_news_entity_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/news/entity/{id} with auth → proxied to S5 with entity_id param."""
    authed_mock_clients.content_store.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/news/entity/{entity_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.content_store.get.assert_called_once()
    call_kwargs = authed_mock_clients.content_store.get.call_args[1]
    # Verify entity_id is passed as a query param to S5
    assert call_kwargs["params"]["entity_id"] == entity_id


# ── F-02: Public proxy routes forward system JWT headers ──────────────────────


@pytest.mark.asyncio
async def test_news_top_sends_system_jwt_header(app, mock_clients) -> None:
    """F-02: GET /v1/news/top (public) sends X-Internal-JWT system header to S5."""
    _inject_rsa_keys(app)
    mock_clients.content_store.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"limit": "5"})

    assert resp.status_code == 200
    # Verify X-Internal-JWT was sent to the downstream
    call_kwargs = mock_clients.content_store.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})
    # Verify the JWT is decodable and has system claims
    from api_gateway.jwt_utils import decode_internal_jwt

    token = call_kwargs["headers"]["X-Internal-JWT"]
    payload = decode_internal_jwt(token, app.state.rsa_public_key)
    assert payload["sub"] == "system:api-gateway"
    assert payload["role"] == "system"
