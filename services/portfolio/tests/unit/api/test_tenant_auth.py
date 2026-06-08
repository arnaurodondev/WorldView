"""Unit tests for tenant endpoint auth (SEC-005 fix — role=system required).

POST /tenants requires request.state.role == "system" (set by InternalJWTMiddleware).
GET /tenants/{id} has no role restriction (read-only via JWT middleware).

Auth model updated by PRD-0025 Wave C: old X-Internal-Token replaced by RS256 JWT.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow, get_uow
from portfolio.api.routes.tenant import router as tenant_router
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from starlette.types import ASGIApp

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _InjectRoleMiddleware(BaseHTTPMiddleware):
    """Test middleware that injects a ``role`` into request.state."""

    def __init__(self, app: ASGIApp, role: str) -> None:
        super().__init__(app)
        self._role = role

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.role = self._role
        return await call_next(request)


def _make_app(uow: FakeUnitOfWork, inject_role: str | None = None) -> FastAPI:
    """Create a minimal FastAPI app with only the tenant router."""
    from portfolio.api.exception_handlers import domain_error_handler
    from portfolio.domain.errors import DomainError

    app = FastAPI()

    if inject_role is not None:
        app.add_middleware(_InjectRoleMiddleware, role=inject_role)

    async def override_uow():  # type: ignore[return]
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    # GET /tenants/{id} uses ReadUoWDep (R27) — override read dep too so the
    # test app doesn't try to open a real DB session via read_factory.
    app.dependency_overrides[get_read_uow] = override_uow
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.include_router(tenant_router, prefix="/api/v1")
    return app


async def test_create_tenant_without_role_returns_401() -> None:
    """POST /tenants without system role → 401 (SEC-005)."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)  # no role injected → request.state.role is None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/tenants", json={"name": "ACME"})
    assert resp.status_code == 401


async def test_create_tenant_wrong_role_returns_401() -> None:
    """POST /tenants with role=user → 401 (SEC-005)."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="user")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/tenants", json={"name": "ACME"})
    assert resp.status_code == 401


async def test_create_tenant_system_role_succeeds() -> None:
    """POST /tenants with role=system → 201."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="system")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/tenants", json={"name": "ACME"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "ACME"


async def test_get_tenant_no_role_restriction() -> None:
    """GET /tenants/{id} does not require role=system."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)  # no role injected
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/tenants/{uuid4()}")
    # 404 (not found) — not 401 or 403
    assert resp.status_code == 404
