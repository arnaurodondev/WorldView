"""Unit tests for PLAN-0064 Wave 4 — GET /v1/search document search proxy.

Tests coverage:
  - 401 when no JWT (guard fires before downstream call)
  - 200 with valid JWT, response proxied from S6
  - All query params forwarded unchanged
  - X-Internal-JWT forwarded to S6 via _auth_headers
  - 502/5xx propagated from downstream timeout
  - 503 propagated when S6 returns 503
  - Rate-limiting middleware is active (route is not exempt)

Uses shared conftest fixtures:
  - ``app`` / ``mock_clients`` — unauthenticated (no Bearer injection)
  - ``authed_app`` / ``authed_mock_clients`` — authenticated (Bearer → user state)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# All tests in this module are fast unit tests (no external I/O).
pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────

# Test JWT: sub + tenant_id match what TestAuthMiddleware in conftest injects.
_JWT_SECRET = "test-secret"  # noqa: S105
_JWT_PAYLOAD = {"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}


def _make_jwt() -> str:
    """Issue a HS256 test JWT. conftest's TestAuthMiddleware decodes it without
    signature verification and populates request.state.user from the payload."""
    return jwt.encode(_JWT_PAYLOAD, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response that the fake ServiceClients will return."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    # Make .json() available for any code that inspects the body before proxying.
    try:
        resp.json = MagicMock(return_value=json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


# ── T-W6-4-01a: unauthenticated → 401 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_401_without_jwt(app, mock_clients) -> None:
    """GET /v1/search without a Bearer token must return 401.

    WHY: _search_documents() guards with `if not request.state.user` — with
    no auth middleware injecting the user, request.state.user is unset so
    getattr returns None → guard triggers → HTTPException(401).
    The downstream nlp_pipeline client must NEVER be called.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/search", params={"q": "apple earnings"})

    assert resp.status_code == 401
    # Guard must prevent any downstream call.
    mock_clients.nlp_pipeline.get.assert_not_called()


# ── T-W6-4-01b: authenticated → 200 proxied ──────────────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_200_with_jwt_forwards_response(authed_app, authed_mock_clients) -> None:
    """GET /v1/search with valid JWT → 200 response body proxied from S6.

    WHY: the proxy should pass S6's raw bytes through unchanged so the
    frontend receives the full SearchDocumentsResponse shape without any
    gateway-level transformation.
    """
    s6_body = json.dumps(
        {
            "query": "apple earnings",
            "total": 2,
            "page": 1,
            "page_size": 25,
            "has_more": False,
            "results": [],
            "facets": [],
            "latency_ms": 42,
        }
    ).encode()
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, s6_body),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "apple earnings"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "apple earnings"
    assert body["total"] == 2
    authed_mock_clients.nlp_pipeline.get.assert_called_once()


# ── T-W6-4-01c: all query params forwarded unchanged ─────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_forwards_all_query_params(authed_app, authed_mock_clients) -> None:
    """GET /v1/search forwards q, entity_id, page_size, source_type to S6.

    WHY `params=dict(request.query_params)`: we deliberately forward *all*
    query params rather than an allowlist so new S6 params don't require a
    gateway change. This test verifies the forwarding is intact.

    NOTE: entity_id can be repeated (FastAPI list[UUID] semantics).  httpx
    serialises repeated params correctly; we use a single entity_id here for
    simplicity — the repeated-param case is tested by the S6 contract.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            b'{"query":"q","total":0,"page":1,"page_size":10,"has_more":false,"results":[],"facets":[],"latency_ms":5}',
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={
                "q": "NVDA guidance",
                "source_type": "sec_edgar",
                "page": "2",
                "page_size": "10",
            },
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.nlp_pipeline.get.assert_called_once()

    # Inspect forwarded params — call_args[1]["params"] is the dict passed to S6.
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    forwarded = call_kwargs["params"]
    assert forwarded.get("q") == "NVDA guidance"
    assert forwarded.get("source_type") == "sec_edgar"
    assert forwarded.get("page") == "2"
    assert forwarded.get("page_size") == "10"


# ── T-W6-4-01d: X-Internal-JWT forwarded to S6 ───────────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_includes_auth_headers_to_s6(authed_app, authed_mock_clients) -> None:
    """_auth_headers() must be called — X-Internal-JWT forwarded to S6.

    WHY: S6 has InternalJWTMiddleware which rejects requests without a valid
    internal JWT.  _auth_headers() issues a fresh RS256 JWT per call; in unit
    tests (no RSA keys) it falls back to reading X-Internal-JWT from the
    inbound request.  We verify the headers dict is passed to the S6 call at
    all — the specific JWT value is tested by _auth_headers() unit tests.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            b'{"query":"q","total":0,"page":1,"page_size":25,"has_more":false,"results":[],"facets":[],"latency_ms":1}',
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "test"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    # _auth_headers() must have been called; it returns a dict (possibly empty
    # in tests without RSA keys).  The important invariant is that `headers`
    # is present — never omitted — so the argument is always forwarded.
    assert "headers" in call_kwargs, "S6 call must include headers= argument"


# ── T-W6-4-01e: downstream timeout → 5xx propagated ─────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_502_on_downstream_timeout(authed_app, authed_mock_clients) -> None:
    """If S6 raises httpx.TimeoutException, the proxy returns 503.

    WHY: the proxy catches ``httpx.TimeoutException`` and raises ``HTTPException(503)``
    so the frontend can show a retry message rather than a generic 500 error.
    This matches the convention used by ``get_morning_briefing()`` and
    ``get_instrument_briefing()``.
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        side_effect=httpx.TimeoutException("S6 timeout"),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "timeout test"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # TimeoutException → HTTPException(503) by the proxy's try/except block.
    assert resp.status_code == 503


# ── T-W6-4-01f: downstream 503 propagated to client ─────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_propagates_503(authed_app, authed_mock_clients) -> None:
    """If S6 returns 503 (e.g. overloaded), the proxy passes it through.

    WHY: the proxy returns
    ``Response(content=resp.content, status_code=resp.status_code)`` so any
    S6 error code is forwarded unchanged.  This lets the frontend distinguish
    between a permanent error (404) and a transient one (503) and act accordingly
    (retry backoff vs surfacing an error message).
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "503 test"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503


# ── T-W6-4-01g: rate limiting middleware is active ───────────────────────────


@pytest.mark.asyncio
async def test_search_proxy_global_rate_limit_active(authed_app, authed_mock_clients) -> None:
    """GET /v1/search runs through the global rate-limiting middleware.

    WHY: S9's RateLimitMiddleware applies to ALL routes unless explicitly
    exempted. This test verifies the route is not accidentally exempted by
    confirming it does NOT return 403/404 from a misconfigured exclusion, and
    that the middleware's Valkey incr/expire probes are called.

    The test app fixture (conftest.py) mounts a mock Valkey where
    ``incr()`` returns 1 (first request in window — always under limit), so
    the request should succeed (200) and not be rate-limited (429).
    """
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            b'{"query":"q","total":0,"page":1,"page_size":25,"has_more":false,"results":[],"facets":[],"latency_ms":1}',
        ),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/search",
            params={"q": "rate limit test"},
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # Route must be reachable — 404 would indicate a routing misconfiguration;
    # 403 would indicate a permissions misconfiguration.
    assert resp.status_code not in (403, 404)
    # Rate-limiting Valkey incr() should have been called — confirms middleware ran.
    authed_app.state.valkey.incr.assert_called()
