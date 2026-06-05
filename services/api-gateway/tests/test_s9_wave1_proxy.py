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
    import json as _json

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    # WHY: proxy code calls resp.json() to parse the body; MagicMock.spec=httpx.Response
    # creates a stub that returns another MagicMock by default. Provide the actual
    # parsed dict so JSON serialisation in the proxy doesn't fail.
    try:
        resp.json = MagicMock(return_value=_json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
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
        resp = await client.get("/v1/ohlcv/00000000-0000-0000-0000-000000000001")

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
            "/v1/ohlcv/00000000-0000-0000-0000-000000000001",
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
            "/v1/ohlcv/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.market_data.get.assert_called_once()
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert "/api/v1/ohlcv/00000000-0000-0000-0000-000000000001" in call_args[0]


# ── Quotes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quotes_single_proxy_fallback(authed_app, authed_mock_clients) -> None:
    """GET /v1/quotes/{id} falls back to legacy S3 quote endpoint when PriceSnapshot returns 404.

    PLAN-0036 W1-10: the route first tries /internal/v1/price/{id}; on 404 it
    falls back to /api/v1/quotes/{id}. When PriceSnapshot is not yet deployed
    (or no snapshot exists), the user still gets a valid response from the
    legacy path.
    """

    def _side_effect(path: str, **kwargs: object) -> object:
        if "/internal/v1/price/" in path:
            return _mock_response(404, b'{"detail": "not found"}')
        # legacy quote path
        legacy = (
            b'{"instrument_id": "00000000-0000-0000-0000-000000000001", "last": "150.0", "bid": null,'
            b' "ask": null, "volume": null, "timestamp": "2026-04-24T00:00:00Z",'
            b' "updated_at": "2026-04-24T00:00:00Z"}'
        )
        return _mock_response(200, legacy)

    authed_mock_clients.market_data.get = AsyncMock(side_effect=_side_effect)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/quotes/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # Two calls: first to PriceSnapshot (404), then to legacy quote endpoint
    assert authed_mock_clients.market_data.get.call_count == 2
    calls = [c[0][0] for c in authed_mock_clients.market_data.get.call_args_list]
    assert any("/internal/v1/price/00000000-0000-0000-0000-000000000001" in c for c in calls)
    assert any("/api/v1/quotes/00000000-0000-0000-0000-000000000001" in c for c in calls)


@pytest.mark.asyncio
async def test_quotes_single_proxy_price_snapshot(authed_app, authed_mock_clients) -> None:
    """GET /v1/quotes/{id} returns enriched quote when PriceSnapshot succeeds.

    PLAN-0036 W1-10: when S3 /internal/v1/price/{id} returns a valid
    PriceSnapshotResponse, the enriched quote (with freshness_status, source,
    etc.) is returned directly — the legacy endpoint is NOT called.
    """
    import json

    snapshot = {
        "instrument_id": "00000000-0000-0000-0000-000000000001",
        "symbol": "AAPL",
        "exchange": "US",
        "price": "150.00",
        "price_change": "2.50",
        "price_change_pct": "1.69",
        "timestamp": "2026-04-24T15:00:00Z",
        "fetched_at": "2026-04-24T15:01:00Z",
        "source": "fresh_quote",
        "freshness_status": "live",
        "stale_reason": None,
        "refresh_available": True,
        "refresh_cooldown_remaining_sec": 0,
    }
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, json.dumps(snapshot).encode()),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/quotes/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    # Enriched freshness fields must be present
    assert body["freshness_status"] == "live"
    assert body["source"] == "fresh_quote"
    assert body["price"] == 150.0
    # Only one call (PriceSnapshot succeeded — no fallback needed)
    authed_mock_clients.market_data.get.assert_called_once()


@pytest.mark.asyncio
async def test_quotes_batch_body_forwarded(authed_app, authed_mock_clients) -> None:
    """POST /v1/quotes/batch forwards request body to the S3 legacy endpoint.

    PLAN-0036 W1-10: the route first tries /internal/v1/price/batch (PriceSnapshot
    batch). When that returns 404 (not yet deployed), it falls back to the legacy
    /api/v1/quotes/batch endpoint. This test verifies the body is forwarded correctly
    to the legacy endpoint on the fallback path.
    """

    def _side_effect(path: str, **kwargs: object) -> object:
        if "/internal/v1/price/batch" in path:
            return _mock_response(404, b'{"detail": "not found"}')
        # legacy batch quote path
        return _mock_response(200, b'{"quotes": []}')

    authed_mock_clients.market_data.post = AsyncMock(side_effect=_side_effect)

    body = b'{"instrument_ids": ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]}'
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
    # Two calls: PriceSnapshot batch (404) then legacy batch endpoint
    assert authed_mock_clients.market_data.post.call_count == 2
    calls = authed_mock_clients.market_data.post.call_args_list
    # Verify the body was forwarded to both endpoints (same body used in fallback)
    legacy_call = next(c for c in calls if "/api/v1/quotes/batch" in c[0][0])
    assert legacy_call[1]["content"] == body


# ── Fundamentals ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fundamentals_proxy_unauthenticated(app, mock_clients) -> None:
    """GET /v1/fundamentals/{id} without auth → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/fundamentals/00000000-0000-0000-0000-000000000001")

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
            "/v1/fundamentals/00000000-0000-0000-0000-000000000001",
            params={"fields": "pe_ratio"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.market_data.get.call_args[1]
    assert call_kwargs["params"].get("fields") == "pe_ratio"
    # Verify downstream path includes instrument_id
    call_args = authed_mock_clients.market_data.get.call_args[0]
    assert "/api/v1/fundamentals/00000000-0000-0000-0000-000000000001" in call_args[0]


# ── Entity Graph + Contradictions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_graph_depth_param(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/graph?depth=2 forwards depth param to S7.

    The response is transformed from S7's GraphNeighborhoodResponse to the
    frontend EntityGraph format by _transform_graph_response() in the route
    handler. The mock must return a valid S7 payload so the transform succeeds.
    """
    entity_id = "00000000-0000-0000-0000-000000000001"

    # Provide a minimal but valid S7 GraphNeighborhoodResponse so the gateway's
    # _transform_graph_response() can parse it without raising TypeError.
    s7_payload = {
        "center": {"entity_id": entity_id, "canonical_name": "Test Corp.", "entity_type": "company"},
        "relations": [],
        "entities": {},
    }
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = s7_payload

    authed_mock_clients.knowledge_graph.get = AsyncMock(return_value=mock_resp)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/graph",
            params={"depth": "2"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    # ISSUE-5 fix (2026-05-10): depth IS now forwarded to S7. The previous behaviour
    # stripped depth because the comment in proxy.py was wrong — S7 has a depth param
    # (ge=1, le=3) for AGE Cypher multi-hop traversal. depth>1 is forwarded; depth=1
    # is omitted (S7 default) to avoid a redundant param on the common case.
    # The `limit` param IS always forwarded (defaulting to 40 when not provided).
    # BP-S9-GRAPH-001: depth>1 triggers a second depth=1 merge call (2 calls total).
    assert authed_mock_clients.knowledge_graph.get.call_count >= 1
    # Use the FIRST call (the primary depth>1 request) for the depth assertion.
    primary_call_kwargs = authed_mock_clients.knowledge_graph.get.call_args_list[0][1]
    assert "depth" in primary_call_kwargs["params"], "depth must be forwarded to S7 when >1 (ISSUE-5)"
    assert primary_call_kwargs["params"]["depth"] == "2", "depth value must be forwarded as string"
    call_kwargs = primary_call_kwargs
    assert "limit" in call_kwargs["params"], "limit is always forwarded to S7"
    call_args = authed_mock_clients.knowledge_graph.get.call_args[0]
    assert f"/api/v1/entities/{entity_id}/graph" in call_args[0]
    # Verify response is transformed to EntityGraph format (not raw S7 shape)
    body = resp.json()
    assert "entity_id" in body
    assert "nodes" in body
    assert "edges" in body


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
    """GET /v1/news/top works without authentication (public endpoint, PRD-0026 §6.7 Flow C)."""
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"hours": "24", "limit": "10"})

    assert resp.status_code == 200
    mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = mock_clients.nlp_pipeline.get.call_args
    # Verify path targets S6 NLP Pipeline (not S5 Content Store).
    assert "/api/v1/news/top" in call_args[0][0]
    call_kwargs = call_args[1]
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
    mock_clients.nlp_pipeline.get.assert_not_called()


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
            "/v1/ohlcv/00000000-0000-0000-0000-000000000001",
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
    """GET /v1/news/top when S6 returns 502 → 502 forwarded (public endpoint)."""
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(502, b'{"detail": "Bad Gateway"}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top")

    assert resp.status_code == 502
    mock_clients.nlp_pipeline.get.assert_called_once()


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
    """GET /v1/news/entity/{id} with auth → proxied to S6 as path param (PRD-0026 §6.7 Flow D)."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": [], "total": 0}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/news/entity/{entity_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = authed_mock_clients.nlp_pipeline.get.call_args[0]
    # Verify entity_id is a path segment, NOT a query param (BP-026 guard).
    assert f"/api/v1/entities/{entity_id}/articles" in call_args[0]
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert "entity_id" not in call_kwargs.get("params", {})


# ── F-014: /v1/entities/{entity_id}/articles canonical alias ─────────────────


@pytest.mark.asyncio
async def test_entity_articles_requires_auth(app, mock_clients) -> None:
    """GET /v1/entities/{id}/articles without auth → 401."""
    entity_id = "00000000-0000-0000-0000-000000000001"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/entities/{entity_id}/articles")

    assert resp.status_code == 401
    mock_clients.nlp_pipeline.get.assert_not_called()


@pytest.mark.asyncio
async def test_entity_articles_authenticated(authed_app, authed_mock_clients) -> None:
    """GET /v1/entities/{id}/articles with auth → proxied to S6 entity articles endpoint.

    This is the canonical path alias for /v1/news/entity/{id}.  Both routes proxy
    to S6's GET /api/v1/entities/{entity_id}/articles endpoint.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": [], "total": 0}'),
    )

    entity_id = "00000000-0000-0000-0000-000000000002"
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/articles",
            params={"limit": "5"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()
    call_args = authed_mock_clients.nlp_pipeline.get.call_args[0]
    # Verify entity_id is a path segment routed to S6's entity articles endpoint.
    assert f"/api/v1/entities/{entity_id}/articles" in call_args[0]
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    # Verify entity_id is NOT leaked as a query parameter.
    assert "entity_id" not in call_kwargs.get("params", {})


# ── F-02: Public proxy routes forward system JWT headers ──────────────────────


@pytest.mark.asyncio
async def test_news_top_sends_system_jwt_header(app, mock_clients) -> None:
    """F-02: GET /v1/news/top (public) sends X-Internal-JWT system header to S6 (nlp-pipeline).

    Route was changed from S5 (content-store) to S6 (nlp-pipeline) in PLAN-0029.
    """
    _inject_rsa_keys(app)
    mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"articles": []}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/news/top", params={"limit": "5"})

    assert resp.status_code == 200
    # Verify X-Internal-JWT was sent to the downstream S6 endpoint
    call_kwargs = mock_clients.nlp_pipeline.get.call_args[1]
    assert "X-Internal-JWT" in call_kwargs.get("headers", {})
    # Verify the JWT is decodable and has system claims
    from api_gateway.jwt_utils import decode_internal_jwt

    token = call_kwargs["headers"]["X-Internal-JWT"]
    payload = decode_internal_jwt(token, app.state.rsa_public_key)
    assert payload["sub"] == "system:api-gateway"
    assert payload["role"] == "system"
