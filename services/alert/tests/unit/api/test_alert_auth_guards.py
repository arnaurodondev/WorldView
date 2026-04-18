"""Unit tests for S10 alert endpoint auth guards (T-D-1-10)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from alert.app import create_app
from alert.config import Settings
from alert.infrastructure.websocket.manager import ConnectionManager
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_app(*, internal_jwt_skip_verification: bool = True) -> object:
    """Create a wired app for auth guard tests.

    ``internal_jwt_skip_verification`` defaults to True so that JWT tokens are
    decoded without signature verification (no public key loaded in unit tests).
    F-001: The middleware now returns 503 by default when the key is missing.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        service_name="alert-auth-test",
        log_json=False,
        s8_internal_token="test-s8",
        s1_internal_token="test-s1",
        internal_jwt_skip_verification=internal_jwt_skip_verification,
    )
    app = create_app(settings)
    # Wire minimal state so routes can run past the dependency injection
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory
    app.state.read_factory = mock_factory
    app.state.ws_manager = ConnectionManager()
    return app


def _make_jwt(user_id: str = "user-123", tenant_id: str = "tenant-456") -> str:
    """Make a HS256 JWT that decodes without signature verification."""
    return jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "secret",
        algorithm="HS256",
    )


@pytest.mark.asyncio
async def test_pending_alerts_requires_auth() -> None:
    """No X-Internal-JWT header → 401 before reaching route."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/alerts/pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ack_requires_auth() -> None:
    """No X-Internal-JWT header → 401 for DELETE /alerts/{id}/ack."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/v1/alerts/{uuid.uuid4()}/ack")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pending_alerts_user_id_not_accepted_as_query_param() -> None:
    """user_id must NOT be accepted via query param after PRD-0025 migration.

    The InternalJWTMiddleware rejects missing X-Internal-JWT before reaching the route.
    Passing user_id as query param alone (without a valid JWT) must still return 401.
    """
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/alerts/pending?user_id={uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pending_alerts_with_valid_jwt_does_not_return_401() -> None:
    """A request with X-Internal-JWT passes middleware and reaches the route.

    The middleware decodes without key verification when public key is not loaded
    (unit test scenario — no S9 JWKS endpoint). Status code may be 500 (no DB)
    but must NOT be 401 (auth failure).
    """
    from unittest.mock import patch

    app = _make_app()
    token = _make_jwt(user_id=str(uuid.uuid4()))

    _PENDING_REPO = "alert.infrastructure.db.repositories.pending_alert.PendingAlertRepository"
    _ALERT_REPO = "alert.infrastructure.db.repositories.alert.AlertRepository"

    with (
        patch(_PENDING_REPO) as MockPendingRepo,
        patch(_ALERT_REPO),
    ):
        MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": token})
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_ack_with_valid_jwt_does_not_return_401() -> None:
    """DELETE /alerts/{id}/ack with JWT passes middleware (401-free), may fail on DB."""
    from unittest.mock import patch

    app = _make_app()
    token = _make_jwt(user_id=str(uuid.uuid4()))

    _PENDING_REPO = "alert.infrastructure.db.repositories.pending_alert.PendingAlertRepository"

    with patch(_PENDING_REPO) as MockPendingRepo:
        MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/alerts/{uuid.uuid4()}/ack", headers={"X-Internal-JWT": token})
    assert resp.status_code != 401
