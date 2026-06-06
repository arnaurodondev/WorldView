"""Contract tests for S9 api-gateway proxy routers (TASK-W3-02).

The audit (BACKEND-AUDIT-REPORT.md) flagged that S9 proxies 9 backend services
with only 3 integration tests — that's a wide blast radius for any regression
in path mapping, header forwarding, or error translation.

This file adds ~12 contract tests across the 10 largest proxy routers. Each
test pins down the *gateway-side contract*: the path-to-backend mapping, the
``X-Internal-JWT`` forwarding, JWT-claim propagation (tenant_id / user_id),
and HTTP error pass-through (404 / 422 / 5xx).

The tests intentionally mock the downstream service clients (``ServiceClients``
on ``app.state.clients``) using the same ``MagicMock`` + ``AsyncMock`` pattern
established in ``tests/test_s9_wave1_proxy.py`` and ``tests/conftest.py`` — we
do NOT introduce a new mocking library (respx, MockTransport, etc.). This
keeps the contract tests cheap and consistent with the rest of the suite.

Covered routers (top 10 by line count):
    1. portfolio.py        — POST /v1/portfolios, GET /v1/brokerage-connections
    2. market.py           — POST /v1/fundamentals/screen
    3. auth.py             — (covered by tests/integration/test_auth_flow.py)
    4. intelligence.py     — POST /v1/entities/{id}/refresh, GET /intelligence
    5. risk_metrics.py     — composition-heavy, not a clean proxy → skipped here
    6. chat.py             — POST /v1/chat
    7. instruments.py      — GET /v1/search
    8. content.py          — GET /v1/documents/{id}
    9. alerts.py           — DELETE /v1/alerts/{id}/ack, PATCH .../acknowledge
   10. (already covered)   — many wave1/wave2/wave3 endpoints under intel/news

NOTES:
- These are *contract* tests, not behavioural tests for the downstream
  service. We assert path/headers/status pass-through, not response bodies.
- ``X-Internal-JWT`` assertions require the ``authed_app_with_rsa`` fixture
  (which wires real RSA keys into ``app.state``) so ``_auth_headers()`` issues
  a fresh RS256 JWT; otherwise the helper silently returns ``{}`` because no
  inbound ``X-Internal-JWT`` is present on test requests.
- ``risk_metrics.py`` is a composition endpoint that calls S1 *and* S3 with
  conditional logic — it's not a pass-through proxy, so a single-mock
  contract test would be brittle. The wave1 file already covers its
  dependency endpoints (OHLCV / value-history) so this gap is acceptable.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# All tests in this module are unit-level (no real network, no real DB).
pytestmark = pytest.mark.unit


# ── Test helpers ─────────────────────────────────────────────────────────────
# Shared HS256 JWT used by the ``inject_user_from_bearer`` test middleware in
# conftest._build_app(). The token is decoded *without* signature verification
# by that middleware, so the secret only needs to be syntactically valid.
_JWT_SECRET = "test-secret"  # noqa: S105 — non-secret test constant
_JWT_PAYLOAD = {
    "sub": "01900000-0000-7000-8000-000000000001",
    "user_id": "01900000-0000-7000-8000-000000000001",
    "tenant_id": "01900000-0000-7000-8000-000000000002",
    "exp": 9999999999,
}


def _make_jwt() -> str:
    """Return an HS256 token shaped like an OIDC access token."""
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a ``httpx.Response``-shaped mock that also implements ``.json()``.

    The proxy code path occasionally calls ``resp.json()`` (e.g. screener
    transform), so we eagerly parse the payload and stub it back. Falling
    back to ``{}`` when the content isn't JSON keeps the helper resilient.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    try:
        resp.json = MagicMock(return_value=json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


# ─── 1. portfolio.py — POST /v1/portfolios (creation) ────────────────────────


@pytest.mark.asyncio
async def test_portfolio_create_maps_path_and_injects_owner_from_jwt(
    authed_app_with_rsa,
    rsa_authed_mock_clients,
) -> None:
    """POST /v1/portfolios → S1 /api/v1/portfolios, with ``owner_user_id`` from JWT.

    Contract:
      - Path mapping: /v1/portfolios → /api/v1/portfolios
      - JWT claim propagation: ``user_id`` is injected into the request body
        (never trust client-supplied owner_user_id — that would allow
        account-takeover; see portfolio.py comment).
      - ``X-Internal-JWT`` is forwarded so S1 InternalJWTMiddleware accepts
        the request.
    """
    rsa_authed_mock_clients.portfolio.post = AsyncMock(
        return_value=_mock_response(201, b'{"portfolio_id": "p-1"}'),
    )

    transport = ASGITransport(app=authed_app_with_rsa)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/portfolios",
            content=b'{"name": "Growth", "currency": "USD"}',
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201
    rsa_authed_mock_clients.portfolio.post.assert_called_once()

    # Verify path mapping to S1.
    call_args = rsa_authed_mock_clients.portfolio.post.call_args
    assert call_args[0][0] == "/api/v1/portfolios"

    # Verify owner_user_id was injected from JWT, not from client body.
    forwarded_body = json.loads(call_args[1]["content"])
    assert forwarded_body["owner_user_id"] == _JWT_PAYLOAD["user_id"]
    assert forwarded_body["name"] == "Growth"  # client fields preserved

    # Verify X-Internal-JWT was forwarded so S1 accepts the request.
    assert "X-Internal-JWT" in call_args[1]["headers"]


@pytest.mark.asyncio
async def test_portfolio_list_backend_404_propagates(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/portfolios with backend 404 → S9 returns 404 (not 500).

    Error-translation contract: S1 errors are passed through verbatim so
    the frontend can render the correct empty-state / not-found UI.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
    authed_mock_clients.portfolio.get.assert_called_once_with(
        "/api/v1/portfolios",
        headers=authed_mock_clients.portfolio.get.call_args[1]["headers"],
    )


# ─── 2. portfolio.py (brokerage) — GET /v1/brokerage-connections ─────────────


@pytest.mark.asyncio
async def test_brokerage_connections_list_forwards_query_params(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/brokerage-connections?portfolio_id=X → S1 with query params intact.

    Contract: query parameters are forwarded unchanged. Path maps to
    /api/v1/brokerage-connections on S1.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(200, b'{"connections": []}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/brokerage-connections",
            params={"portfolio_id": "p-123"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.portfolio.get.call_args
    assert call_args[0][0] == "/api/v1/brokerage-connections"
    assert call_args[1]["params"].get("portfolio_id") == "p-123"


# ─── 3. market.py — POST /v1/fundamentals/screen (screener) ──────────────────


@pytest.mark.asyncio
async def test_screener_post_maps_path_and_forwards_body(
    app,  # public endpoint — uses system JWT, doesn't require user auth
    mock_clients,
) -> None:
    """POST /v1/fundamentals/screen → S3 /api/v1/fundamentals/screen.

    Contract:
      - Path mapping to S3 market-data.
      - Request body forwarded verbatim.
      - 200 responses are transformed (flat metrics), but the *contract* tests
        below only assert pass-through path + status.
    """
    # S3 returns the nested-metrics shape; gateway flattens it.
    s3_payload = json.dumps(
        {
            "results": [{"ticker": "AAPL", "metrics": {"market_capitalization": 3e12}}],
            "total": 1,
            "count": 1,
            "offset": 0,
            "limit": 50,
        }
    ).encode()
    mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(200, s3_payload),
    )

    body = b'{"filters": [{"field": "market_cap", "op": ">", "value": 1e12}]}'
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/fundamentals/screen",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    call_args = mock_clients.market_data.post.call_args
    assert call_args[0][0] == "/api/v1/fundamentals/screen"
    # Request body is forwarded unchanged.
    assert call_args[1]["content"] == body


@pytest.mark.asyncio
async def test_screener_backend_422_propagates_unchanged(
    app,
    mock_clients,
) -> None:
    """POST /v1/fundamentals/screen with backend 422 → S9 returns 422.

    Contract: validation errors from S3 (e.g. unknown metric name) are
    surfaced as 422 so the frontend can display the specific field error.
    """
    mock_clients.market_data.post = AsyncMock(
        return_value=_mock_response(422, b'{"detail": "unknown metric"}'),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/fundamentals/screen",
            content=b'{"filters": [{"field": "bogus", "op": ">", "value": 0}]}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 422
    assert b"unknown metric" in resp.content


# ─── 4. intelligence.py — POST /v1/entities/{id}/refresh (REQ-003) ───────────


@pytest.mark.asyncio
async def test_entity_refresh_proxies_to_knowledge_graph(
    authed_app_with_rsa,
    rsa_authed_mock_clients,
) -> None:
    """POST /v1/entities/{id}/refresh → S7 /api/v1/entities/{id}/refresh.

    Contract (REQ-003):
      - Path mapping to S7 knowledge_graph client.
      - 202 status is preserved.
      - ``X-Internal-JWT`` is forwarded.
      - Request body (refresh_type) is forwarded verbatim.
    """
    entity_id = "00000000-0000-0000-0000-000000000001"
    rsa_authed_mock_clients.knowledge_graph.post = AsyncMock(
        return_value=_mock_response(202, b'{"job_id": "j-1"}'),
    )

    body = b'{"refresh_type": "narrative"}'
    transport = ASGITransport(app=authed_app_with_rsa)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/entities/{entity_id}/refresh",
            content=body,
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 202
    call_args = rsa_authed_mock_clients.knowledge_graph.post.call_args
    assert call_args[0][0] == f"/api/v1/entities/{entity_id}/refresh"
    assert call_args[1]["content"] == body
    # ``X-Internal-JWT`` must be forwarded for S7 to accept the request.
    assert "X-Internal-JWT" in call_args[1]["headers"]


@pytest.mark.asyncio
async def test_entity_intelligence_backend_404_propagates(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/entities/{id}/intelligence with backend 404 → S9 returns 404.

    Contract: when S7 cannot find the entity, the frontend must see 404 so
    the "Entity not found" empty-state renders instead of an error toast.
    """
    entity_id = "00000000-0000-0000-0000-000000000099"
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(404, b'{"detail": "entity not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/intelligence",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 404
    call_args = authed_mock_clients.knowledge_graph.get.call_args
    assert call_args[0][0] == f"/api/v1/entities/{entity_id}/intelligence"


# ─── 5. chat.py — POST /v1/chat ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_post_proxies_to_rag_chat_with_internal_jwt(
    authed_app_with_rsa,
    rsa_authed_mock_clients,
) -> None:
    """POST /v1/chat → S8 /api/v1/chat with ``X-Internal-JWT`` forwarded.

    Contract: chat requires authentication and the downstream rag-chat
    service receives the user identity via the internal JWT (not via
    a header like X-Tenant-ID, which is dead post-PRD-0025).
    """
    rsa_authed_mock_clients.rag_chat.post = AsyncMock(
        return_value=_mock_response(200, b'{"response": "hello"}'),
    )

    transport = ASGITransport(app=authed_app_with_rsa)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat",
            content=b'{"message": "hi"}',
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    call_args = rsa_authed_mock_clients.rag_chat.post.call_args
    assert call_args[0][0] == "/api/v1/chat"
    # The internal JWT must be present AND decodable to a token claiming the
    # caller's tenant — that's how downstream services authorise per-tenant
    # data access.
    internal_jwt = call_args[1]["headers"].get("X-Internal-JWT")
    assert internal_jwt is not None, "X-Internal-JWT must be forwarded"
    decoded = jwt.decode(
        internal_jwt,
        options={"verify_signature": False, "verify_aud": False},
    )
    assert decoded["tenant_id"] == _JWT_PAYLOAD["tenant_id"]


# ─── 6. instruments.py — GET /v1/search (document search) ────────────────────


@pytest.mark.asyncio
async def test_search_forwards_query_params_to_nlp_pipeline(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/search?q=foo → S6 /api/v1/search/documents with q forwarded.

    Contract: full-text search across articles + filings. The gateway
    forwards every query param (q, entity_id, scope, etc.) unchanged.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, b'{"hits": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "earnings", "scope": "articles", "page_size": "20"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.nlp_pipeline.get.call_args
    assert call_args[0][0] == "/api/v1/search/documents"
    assert call_args[1]["params"].get("q") == "earnings"
    assert call_args[1]["params"].get("scope") == "articles"
    assert call_args[1]["params"].get("page_size") == "20"


# ─── 7. content.py — GET /v1/documents/{doc_id} ──────────────────────────────


@pytest.mark.asyncio
async def test_document_get_propagates_tenant_id_header(
    authed_app_with_rsa,
    rsa_authed_mock_clients,
) -> None:
    """GET /v1/documents/{id} → S4 with ``X-Tenant-ID`` + internal JWT.

    Contract: ``_document_headers()`` enriches the request with X-Tenant-ID
    and X-User-ID *in addition to* the internal JWT. S4's deps look at both,
    so the gateway must forward both.
    """
    doc_id = "doc-abc-123"
    rsa_authed_mock_clients.content_ingestion.get = AsyncMock(
        return_value=_mock_response(200, b'{"doc_id": "doc-abc-123", "status": "ready"}'),
    )

    transport = ASGITransport(app=authed_app_with_rsa)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = rsa_authed_mock_clients.content_ingestion.get.call_args
    assert call_args[0][0] == f"/api/v1/documents/{doc_id}"
    headers = call_args[1]["headers"]
    # tenant_id from JWT claim must be propagated to S4 via explicit header.
    assert headers.get("X-Tenant-ID") == _JWT_PAYLOAD["tenant_id"]
    assert headers.get("X-User-ID") == _JWT_PAYLOAD["user_id"]
    assert "X-Internal-JWT" in headers


# ─── 8. alerts.py — DELETE /v1/alerts/{id}/ack ───────────────────────────────


@pytest.mark.asyncio
async def test_alert_ack_proxies_to_s10(
    authed_app,
    authed_mock_clients,
) -> None:
    """DELETE /v1/alerts/{id}/ack → S10 /api/v1/alerts/{id}/ack.

    Contract: path mapping to S10 alert service. Returns 200 on success
    (BP-064 says never 204).
    """
    alert_id = "alert-xyz-1"
    authed_mock_clients.alert.delete = AsyncMock(
        return_value=_mock_response(200, b'{"status": "acknowledged"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            f"/v1/alerts/{alert_id}/ack",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.alert.delete.call_args
    assert call_args[0][0] == f"/api/v1/alerts/{alert_id}/ack"


@pytest.mark.asyncio
async def test_alert_acknowledge_sets_no_store_cache_header(
    authed_app,
    authed_mock_clients,
) -> None:
    """PATCH /v1/alerts/{id}/acknowledge → S10 with Cache-Control: no-store.

    Contract: mutations on alerts must never be cached by intermediaries
    (CDN, browser, proxy). The gateway sets ``Cache-Control: no-store`` on
    every PATCH .../acknowledge response.
    """
    alert_id = "alert-xyz-2"
    authed_mock_clients.alert.patch = AsyncMock(
        return_value=_mock_response(200, b'{"status": "acknowledged"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch(
            f"/v1/alerts/{alert_id}/acknowledge",
            content=b"{}",
            headers={
                "Authorization": f"Bearer {_make_jwt()}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    # WHY assert Cache-Control: alerts.py explicitly sets this on the Response.
    assert resp.headers.get("Cache-Control") == "no-store"
    call_args = authed_mock_clients.alert.patch.call_args
    assert call_args[0][0] == f"/api/v1/alerts/{alert_id}/acknowledge"


# ─── 9. intelligence.py — entity narratives proxy ────────────────────────────


@pytest.mark.asyncio
async def test_entity_narratives_backend_503_propagates(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/entities/{id}/narratives with backend 503 → S9 returns 503.

    Contract: downstream availability errors are surfaced unchanged so
    monitoring can attribute outages to the right service tier.
    """
    entity_id = "00000000-0000-0000-0000-000000000003"
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/entities/{entity_id}/narratives",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503
    call_args = authed_mock_clients.knowledge_graph.get.call_args
    assert f"/api/v1/entities/{entity_id}/narratives" in call_args[0][0]


# ─── 10. market.py — GET /v1/fundamentals/{id}/snapshot ──────────────────────


@pytest.mark.asyncio
async def test_fundamentals_snapshot_maps_to_market_data(
    authed_app,
    authed_mock_clients,
) -> None:
    """GET /v1/fundamentals/{id}/snapshot → S3 /api/v1/fundamentals/{id}/snapshot.

    Contract: instrument-scoped snapshot is path-mapped to S3 market-data;
    the {instrument_id} segment is preserved verbatim.

    WHY UUID: instrument_id path params are now UUID-typed (F-010 security fix).
    FastAPI auto-validates and returns 422 for non-UUID values.
    """
    # WHY UUID: F-010 — instrument_id is now UUID-typed; non-UUID values → 422.
    instrument_id = "11111111-1111-1111-1111-111111111111"
    authed_mock_clients.market_data.get = AsyncMock(
        return_value=_mock_response(200, b'{"ticker": "AAPL", "pe_ratio": 25.0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/v1/fundamentals/{instrument_id}/snapshot",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_args = authed_mock_clients.market_data.get.call_args
    # Path-mapping contract: instrument_id is positional, not a query param.
    assert call_args[0][0] == f"/api/v1/fundamentals/{instrument_id}/snapshot"
