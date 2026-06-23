"""End-to-end auth + tenant-isolation + 5xx-sanitization boundary tests.

Audit reference: docs/audits/2026-06-22-backend-e2e-coverage-gaps.md (BUG-7).

Before this file the api-gateway had NO e2e directory: the public security
boundary (auth rejection, tenant spoofing, upstream-error leakage) was entirely
untested. These tests lock that boundary from the *outside* — they drive the
real ASGI app through the full middleware stack with only the downstream service
HTTP clients mocked, and assert what a client (or an attacker) actually receives.

Covered contracts:

1. Unauthenticated request to a protected route → 401, with NO internal detail.
2. Invalid / malformed / expired JWT → treated as unauthenticated → 401.
3. Tenant isolation: a client cannot read another tenant's data by spoofing a
   tenant_id / owner id in the request body — the gateway always forwards the
   *verified JWT identity* to the backend, never client-supplied identity. When
   the backend rejects a cross-tenant access (403/404), the gateway forwards
   that status without leaking internal detail.
4. Backend 5xx → client receives a SANITIZED generic error (BUG-7): the raw
   upstream body (stack traces / SQL / internal hostnames) never reaches the
   client, and the status is normalised to 502.

Test harness notes:
- ``authed_app`` decodes the inbound Bearer JWT *without signature verification*
  and injects ``request.state.user`` exactly as ``OIDCAuthMiddleware`` would in
  production (see tests/conftest.py). So a token whose payload omits the claims,
  or which cannot be parsed at all, surfaces as "no authenticated user" — the
  same outcome production has for an invalid/expired RS256 token (the middleware
  sets ``request.state.user = None`` on any decode failure).
- ``app`` (no Bearer injection) models a request that carries no usable identity.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# e2e marker so these run under the default ``-m "not integration"`` selection
# (they need no live infra — downstream clients are mocked) but can also be
# filtered explicitly with ``-m e2e``.
pytestmark = pytest.mark.e2e

_JWT_SECRET = "test-secret"  # noqa: S105 — test-only HS256 signing secret


def _make_jwt(payload: dict) -> str:
    """Encode a test JWT. Signature is irrelevant: the test auth middleware
    decodes with ``verify_signature=False`` (mirroring how production maps any
    valid RS256 token to request.state.user)."""
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _valid_token(tenant_id: str = "tenant-A", user_id: str = "user-A") -> str:
    return _make_jwt({"sub": user_id, "tenant_id": tenant_id, "exp": 9999999999})


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    """A mocked ``httpx.Response`` from a downstream service."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    # ``.text`` is read only on the 5xx logging path; provide a decoded view so
    # the server-side log line is realistic.
    resp.text = content.decode(errors="replace")
    return resp


# ── 1. Unauthenticated access ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_401(app, mock_clients) -> None:
    """No Authorization header on a protected route → 401, no internal leak.

    The downstream client must NOT be called: rejection happens at the gateway
    before any backend round-trip (defence in depth — an unauthenticated request
    never reaches a backend service).
    """
    # Arm the downstream so we can prove it is never invoked.
    mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"[]"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/portfolios")

    assert resp.status_code == 401
    # Generic, caller-safe detail only — no stack trace / module path / hostnames.
    body = resp.json()
    assert body["detail"] == "Authentication required"
    for leak in ("Traceback", 'File "', ".py", "psql", "asyncpg", "tenant-"):
        assert leak not in json.dumps(body)
    # The backend was never contacted.
    mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_jwt_is_rejected_401(authed_app, authed_mock_clients) -> None:
    """A malformed Bearer token cannot be decoded → no user → 401.

    Mirrors production: ``OIDCAuthMiddleware`` sets ``request.state.user = None``
    on any decode/verify failure, so the protected route returns 401.
    """
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"[]"))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authentication required"
    authed_mock_clients.portfolio.get.assert_not_called()


@pytest.mark.asyncio
async def test_expired_jwt_is_rejected_401(app, mock_clients) -> None:
    """An expired RS256 token is rejected by the REAL OIDCAuthMiddleware → 401.

    Unlike the other tests here, this drives the production middleware directly
    (not the simplified ``authed_app`` harness, which does not verify ``exp``).
    We wire ``rsa_public_key`` into app.state so the middleware's dev-login
    branch performs full RS256 + ``require=[iss,sub,exp]`` validation, then send
    a token signed by the matching private key but with ``exp`` in the past. The
    middleware must raise ``ExpiredSignatureError`` internally, leave
    ``request.state.user = None``, and the route must return 401 — the backend is
    never contacted.
    """
    import jwt as pyjwt
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    from tests.conftest import _PRIVATE_PEM, _PUBLIC_PEM

    # The ``app`` fixture has no TestAuthMiddleware, so OIDCAuthMiddleware is the
    # only thing populating request.state.user — exactly the production topology.
    app.state.rsa_public_key = _PUBLIC_PEM  # middleware decodes RS256 with this
    mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(200, b"[]"))

    private_key = load_pem_private_key(_PRIVATE_PEM.encode(), password=None, backend=default_backend())
    expired_token = pyjwt.encode(
        {
            "iss": "worldview-gateway",
            "sub": "user-A",
            "tenant_id": "tenant-A",
            "aud": "worldview-internal",
            "exp": 1,  # 1970 — long expired
            "iat": 0,
        },
        private_key,
        algorithm="RS256",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

    assert resp.status_code == 401
    mock_clients.portfolio.get.assert_not_called()


# ── 2. Tenant isolation / identity spoofing ────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_id_cannot_be_spoofed_via_body(authed_app, authed_mock_clients) -> None:
    """A client cannot create a portfolio owned by another user/tenant.

    Attack: the caller is authenticated as ``user-A`` but puts
    ``owner_user_id: "victim-user"`` in the request body, hoping the gateway
    forwards the attacker-chosen owner. The gateway MUST ignore the body identity
    and forward only the verified JWT ``sub`` to the backend.
    """
    captured: dict = {}

    async def _capture_post(path: str, *, content=None, headers=None, **_kwargs):
        captured["content"] = content
        captured["headers"] = headers or {}
        return _mock_response(201, b'{"id": "p-1"}')

    authed_mock_clients.portfolio.post = AsyncMock(side_effect=_capture_post)

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/portfolios",
            content=json.dumps({"name": "Mine", "currency": "USD", "owner_user_id": "victim-user"}).encode(),
            headers={
                "Authorization": f"Bearer {_valid_token(user_id='user-A')}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 201
    # The body actually forwarded to S1 must carry the VERIFIED identity, not the
    # spoofed one. Inspect the JSON the gateway re-serialised for the backend.
    forwarded = json.loads(captured["content"])
    assert forwarded["owner_user_id"] == "user-A"
    assert forwarded["owner_user_id"] != "victim-user"


@pytest.mark.asyncio
async def test_cross_tenant_backend_rejection_is_forwarded(authed_app, authed_mock_clients) -> None:
    """When the backend denies a cross-tenant access, the gateway forwards the
    403/404 WITHOUT leaking internal detail.

    Scenario: ``user-A`` requests a portfolio that belongs to ``tenant-B``; the
    backend (which enforces tenant scoping) replies 404 (existence-hiding) — the
    gateway must pass that status through and not turn it into a 200 or leak the
    real owner/tenant.
    """
    authed_mock_clients.portfolio.get = AsyncMock(
        # Backend hides existence with 404 + a caller-safe detail.
        return_value=_mock_response(404, b'{"detail": "Portfolio not found"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios/00000000-0000-0000-0000-0000000000bb/concentration",
            headers={"Authorization": f"Bearer {_valid_token(tenant_id='tenant-A')}"},
        )

    # 404 forwarded (client-error semantics preserved); no other tenant's data.
    assert resp.status_code == 404
    body = json.dumps(resp.json())
    assert "tenant-B" not in body
    assert "owner" not in body.lower()


# ── 3. Backend 5xx sanitization (BUG-7) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_backend_5xx_body_is_sanitized(authed_app, authed_mock_clients) -> None:
    """A backend 5xx must never leak its raw body (stack trace / SQL) to client.

    This is the core BUG-7 contract verified end-to-end through the full stack:
    the upstream returns a body containing a stack trace + SQL; the client must
    receive a generic ``{"detail": "upstream service error"}`` envelope with a
    normalised 502 status.
    """
    leaky_body = json.dumps(
        {
            "detail": (
                "Traceback (most recent call last): File /app/db.py line 42 in query "
                'psql ERROR: relation "holdings" does not exist at host 10.0.3.7:5432'
            )
        }
    ).encode()
    authed_mock_clients.portfolio.get = AsyncMock(return_value=_mock_response(500, leaky_body))

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )

    # Status normalised to 502 — gateway is alive, upstream is broken.
    assert resp.status_code == 502
    assert resp.json() == {"detail": "upstream service error"}
    # None of the internal detail may appear in the client-facing body.
    raw = resp.content
    for leak in (b"Traceback", b"db.py", b"psql", b"holdings", b"10.0.3.7", b"5432"):
        assert leak not in raw, f"leaked {leak!r} to client"


@pytest.mark.asyncio
async def test_backend_503_status_preserved_but_body_sanitized(authed_app, authed_mock_clients) -> None:
    """A backend 503 keeps its status (retry/backoff semantics) but the upstream
    body is still sanitized — clients learn "unavailable", never internal detail."""
    authed_mock_clients.portfolio.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "connection pool exhausted on host pg-primary-2"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/portfolios",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )

    assert resp.status_code == 503
    assert b"pool exhausted" not in resp.content
    assert b"pg-primary" not in resp.content
