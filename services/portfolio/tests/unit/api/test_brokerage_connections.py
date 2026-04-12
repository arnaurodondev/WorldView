"""Unit tests for brokerage connections API routes (PRD-0022 §6.2)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow, get_uow
from portfolio.api.exception_handlers import domain_error_handler
from portfolio.api.routes.brokerage_connections import router as brokerage_connections_router
from portfolio.config import Settings
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.enums import ConnectionStatus, SyncErrorType
from portfolio.domain.errors import DomainError

from common.time import utc_now  # type: ignore[import-untyped]
from tests.unit.fakes import FakeBrokerageClient, FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

USER_ID = uuid4()
TENANT_ID = uuid4()
PORTFOLIO_ID = uuid4()
CONNECTION_ID = uuid4()

AUTH_HEADERS = {
    "X-User-Id": str(USER_ID),
    "X-Tenant-Id": str(TENANT_ID),
}


def _make_app(uow: FakeUnitOfWork, brokerage_client: FakeBrokerageClient | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the brokerage connections router."""
    app = FastAPI()
    settings = Settings()  # type: ignore[call-arg]
    app.state.settings = settings
    app.state.brokerage_client = brokerage_client or FakeBrokerageClient()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_read_uow] = override_uow

    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)  # type: ignore[arg-type]

    app.include_router(brokerage_connections_router, prefix="/api/v1")
    return app


# ── POST /brokerage-connections ───────────────────────────────────────────────


async def test_initiate_connection_success() -> None:
    """POST with valid body and auth headers -> 201 with connection_id and redirect_uri."""
    uow = FakeUnitOfWork()
    portfolio = Portfolio(tenant_id=TENANT_ID, owner_id=USER_ID, name="Test Portfolio")
    portfolio.id = PORTFOLIO_ID
    await uow.portfolios.save(portfolio)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/brokerage-connections",
            json={"portfolio_id": str(PORTFOLIO_ID), "snaptrade_tos_accepted": True},
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert "connection_id" in body
    assert "redirect_uri" in body
    assert body["redirect_uri"] == "https://fake-snaptrade.example.com/connect"


async def test_initiate_connection_missing_headers_returns_401() -> None:
    """POST without auth headers -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/brokerage-connections",
            json={"portfolio_id": str(uuid4()), "snaptrade_tos_accepted": True},
        )
    assert resp.status_code == 401


async def test_initiate_connection_tos_not_accepted_returns_422() -> None:
    """POST with snaptrade_tos_accepted=False -> 422 (Pydantic field validator)."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/brokerage-connections",
            json={"portfolio_id": str(uuid4()), "snaptrade_tos_accepted": False},
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 422


# ── GET /brokerage-connections ────────────────────────────────────────────────


async def test_list_connections_empty() -> None:
    """GET with no connections for user -> 200 with empty items list."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/brokerage-connections", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


async def test_list_connections_returns_user_connections() -> None:
    """GET returns only connections belonging to the authenticated user."""
    uow = FakeUnitOfWork()
    conn = BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=ConnectionStatus.ACTIVE,
    )
    await uow.brokerage_connections.save(conn)

    # Connection belonging to a different user — should NOT appear
    other_conn = BrokerageConnection(
        tenant_id=TENANT_ID,
        user_id=uuid4(),
        portfolio_id=uuid4(),
        snaptrade_user_id="other-snap-user",
        snaptrade_user_secret="other-snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
    )
    await uow.brokerage_connections.save(other_conn)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/brokerage-connections", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["connection_id"] == str(CONNECTION_ID)
    assert items[0]["status"] == "active"


async def test_list_connections_missing_headers_returns_401() -> None:
    """GET without auth headers -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/brokerage-connections")
    assert resp.status_code == 401


# ── DELETE /brokerage-connections/{connection_id} ────────────────────────────


async def test_disconnect_connection_success() -> None:
    """DELETE on an ACTIVE connection -> 200 with status=disconnected."""
    uow = FakeUnitOfWork()
    conn = BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=ConnectionStatus.ACTIVE,
    )
    await uow.brokerage_connections.save(conn)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/v1/brokerage-connections/{CONNECTION_ID}",
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"


async def test_disconnect_connection_missing_headers_returns_401() -> None:
    """DELETE without auth headers -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(f"/api/v1/brokerage-connections/{uuid4()}")
    assert resp.status_code == 401


async def test_disconnect_connection_not_found_returns_404() -> None:
    """DELETE on a non-existent connection -> 404."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            f"/api/v1/brokerage-connections/{uuid4()}",
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 404


# ── GET /brokerage-connections/{connection_id}/callback ──────────────────────


async def test_activate_connection_success() -> None:
    """Callback GET on a PENDING connection -> 200 with status=active."""
    from common.time import utc_now  # type: ignore[import-untyped]

    snap_user_id = "snap-user-123"
    uow = FakeUnitOfWork()
    conn = BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id=snap_user_id,
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=ConnectionStatus.PENDING,
    )
    await uow.brokerage_connections.save(conn)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/brokerage-connections/{CONNECTION_ID}/callback",
            params={"authorizationId": "auth-id-1", "userId": snap_user_id, "sessionId": "sess-1"},
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["connection_id"] == str(CONNECTION_ID)


async def test_activate_connection_missing_headers_returns_401() -> None:
    """Callback GET without auth headers -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/brokerage-connections/{uuid4()}/callback",
            params={"authorizationId": "x", "userId": "y", "sessionId": "z"},
        )
    assert resp.status_code == 401


# ── GET /brokerage-connections/{connection_id}/sync-errors ───────────────────


async def test_get_sync_errors_empty() -> None:
    """GET sync-errors with no errors -> 200 with empty items list."""
    uow = FakeUnitOfWork()
    conn = BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=ConnectionStatus.ACTIVE,
    )
    await uow.brokerage_connections.save(conn)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/brokerage-connections/{CONNECTION_ID}/sync-errors",
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


async def test_get_sync_errors_returns_errors() -> None:
    """GET sync-errors with existing errors -> 200 with populated items."""
    uow = FakeUnitOfWork()
    conn = BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=ConnectionStatus.ERROR,
    )
    await uow.brokerage_connections.save(conn)

    error = BrokerageTransactionSyncError(
        connection_id=CONNECTION_ID,
        snaptrade_transaction_id="txn-001",
        error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
        error_detail="Symbol XYZ not found",
    )
    await uow.brokerage_sync_errors.save(error)

    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/brokerage-connections/{CONNECTION_ID}/sync-errors",
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["snaptrade_transaction_id"] == "txn-001"
    assert items[0]["error_detail"] == "Symbol XYZ not found"
    # raw_transaction must NOT be present in response (privacy guard)
    assert "raw_transaction" not in items[0]


async def test_get_sync_errors_not_found_returns_404() -> None:
    """GET sync-errors for non-existent connection -> 404."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/brokerage-connections/{uuid4()}/sync-errors",
            headers=AUTH_HEADERS,
        )
    assert resp.status_code == 404


async def test_get_sync_errors_missing_headers_returns_401() -> None:
    """GET sync-errors without auth headers -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/brokerage-connections/{uuid4()}/sync-errors")
    assert resp.status_code == 401


# ── Schema validator tests ────────────────────────────────────────────────────


def test_initiate_request_tos_false_raises_validation_error() -> None:
    """InitiateBrokerageConnectionRequest rejects snaptrade_tos_accepted=False."""
    from portfolio.api.schemas import InitiateBrokerageConnectionRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        InitiateBrokerageConnectionRequest(portfolio_id=uuid4(), snaptrade_tos_accepted=False)
    errors = exc_info.value.errors()
    assert any("SnapTrade" in str(e["msg"]) for e in errors)


def test_initiate_request_tos_true_passes() -> None:
    """InitiateBrokerageConnectionRequest accepts snaptrade_tos_accepted=True."""
    from portfolio.api.schemas import InitiateBrokerageConnectionRequest

    req = InitiateBrokerageConnectionRequest(portfolio_id=uuid4(), snaptrade_tos_accepted=True)
    assert req.snaptrade_tos_accepted is True
