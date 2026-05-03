"""Tests for PLAN-0068 Wave A-2: GET /v1/fundamentals/earnings-calendar proxy.

Verifies:
  (a) 401 without authentication
  (b) Correct proxy call to S7 with event_type=corporate injected
  (c) Caller cannot override event_type from outside
  (d) S7 downstream error forwarded correctly
  (e) Route not shadowed by /{instrument_id}

PLAN-0068 Wave A-2.
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
    try:
        resp.json = MagicMock(return_value=_json.loads(content.decode()))
    except Exception:
        resp.json = MagicMock(return_value={})
    return resp


def _inject_rsa_keys(application) -> None:
    """Inject real RSA keys into app state so internal JWT issuance works."""
    from api_gateway.oidc import rsa_key_id

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    application.state.rsa_private_key = private_key
    application.state.rsa_public_key = private_key.public_key()
    application.state.rsa_kid = rsa_key_id(private_key.public_key())


# ── Test: 401 without authentication ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_earnings_calendar_requires_auth(app, mock_clients) -> None:
    """GET /v1/fundamentals/earnings-calendar without auth → 401.

    WHY: all dashboard endpoints require a valid JWT so unauthenticated scrapers
    and bots cannot access financial intelligence data.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/fundamentals/earnings-calendar")

    assert resp.status_code == 401


# ── Test: proxies to S7 with event_type=corporate ─────────────────────────────


@pytest.mark.asyncio
async def test_earnings_calendar_proxies_to_s7(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/earnings-calendar → S7 called with event_type=corporate.

    This is the primary assertion: the proxy MUST inject event_type=corporate so
    the S7 temporal-events endpoint returns only earnings events, not macro/geopolitical.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"events": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/earnings-calendar",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    # Critical assertion: event_type must always be "corporate" (BP-340 pattern)
    assert call_kwargs["params"]["event_type"] == "corporate"


@pytest.mark.asyncio
async def test_earnings_calendar_event_type_cannot_be_overridden(authed_app, authed_mock_clients) -> None:
    """Caller cannot override event_type — it must always be 'corporate'.

    WHY: a caller passing ?event_type=macro would see macro data in the
    earnings widget. The proxy must strip and override the param.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"events": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/earnings-calendar?event_type=macro",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    # Despite caller passing event_type=macro, proxy injects corporate
    assert call_kwargs["params"]["event_type"] == "corporate"


@pytest.mark.asyncio
async def test_earnings_calendar_passes_through_date_params(authed_app, authed_mock_clients) -> None:
    """Optional date/limit params are forwarded to S7 unchanged.

    WHY: the widget uses from_date/to_date to scope the 7-day calendar view.
    Stripping them would always return the S7 default window.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"events": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/earnings-calendar?from_date=2026-05-01&to_date=2026-05-07&limit=10",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 200
    call_kwargs = authed_mock_clients.knowledge_graph.get.call_args[1]
    params = call_kwargs["params"]
    assert params["event_type"] == "corporate"
    assert params.get("from_date") == "2026-05-01"
    assert params.get("to_date") == "2026-05-07"
    assert params.get("limit") == "10"


# ── Test: downstream error forwarded ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_earnings_calendar_downstream_error(authed_app, authed_mock_clients) -> None:
    """GET /v1/fundamentals/earnings-calendar when S7 returns 503 → 503 forwarded.

    WHY: the proxy must forward S7's error status unchanged so the frontend
    widget can distinguish "service down" (503) from "no data" (200 empty).
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(503, b'{"detail": "Service Unavailable"}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/earnings-calendar",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    assert resp.status_code == 503


# ── Test: route not shadowed by /{instrument_id} ─────────────────────────────


@pytest.mark.asyncio
async def test_earnings_calendar_not_shadowed_by_instrument_id(authed_app, authed_mock_clients) -> None:
    """earnings-calendar is NOT matched as an instrument_id.

    WHY: FastAPI matches routes in registration order. If /earnings-calendar
    were registered AFTER /{instrument_id}, the literal string "earnings-calendar"
    would be captured as an instrument_id and routed to the wrong handler.
    This test verifies the route is correctly registered before the path param.
    """
    authed_mock_clients.knowledge_graph.get = AsyncMock(
        return_value=_mock_response(200, b'{"events": [], "total": 0}'),
    )

    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/fundamentals/earnings-calendar",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )

    # If shadowed, this would return a different status (likely 404/500 from S3)
    # because "earnings-calendar" would be sent to S3 as an instrument_id.
    # A 200 from knowledge_graph.get confirms correct routing.
    assert resp.status_code == 200
    # Specifically, knowledge_graph.get must have been called (not market_data.get)
    authed_mock_clients.knowledge_graph.get.assert_called_once()
    # market_data must NOT have been called
    authed_mock_clients.market_data.get.assert_not_called()
