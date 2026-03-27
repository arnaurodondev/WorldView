"""Unit tests for tenant endpoint auth (D-001 — X-Internal-Token required)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_uow
from portfolio.api.routes.tenant import router as tenant_router
from portfolio.config import Settings

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

TOKEN = "test-internal-secret"  # noqa: S105


def _make_app(uow: FakeUnitOfWork) -> FastAPI:
    """Create a minimal FastAPI app with only the tenant router."""
    app = FastAPI()
    settings = Settings(internal_service_token=TOKEN)
    app.state.settings = settings

    async def override_uow():
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.include_router(tenant_router, prefix="/api/v1")
    return app


async def test_create_tenant_without_token_returns_401() -> None:
    """POST /tenants without X-Internal-Token -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/tenants", json={"name": "ACME"})
    assert resp.status_code == 401


async def test_create_tenant_wrong_token_returns_401() -> None:
    """POST /tenants with wrong token -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/tenants",
            json={"name": "ACME"},
            headers={"X-Internal-Token": "wrong-token"},
        )
    assert resp.status_code == 401


async def test_create_tenant_valid_token_succeeds() -> None:
    """POST /tenants with valid token -> 201."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/tenants",
            json={"name": "ACME"},
            headers={"X-Internal-Token": TOKEN},
        )
    assert resp.status_code == 201
    assert resp.json()["name"] == "ACME"


async def test_get_tenant_without_token_returns_401() -> None:
    """GET /tenants/{id} without token -> 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/tenants/{uuid4()}")
    assert resp.status_code == 401
