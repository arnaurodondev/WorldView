"""Unit tests for POST /internal/v1/users/provision (PRD-0025 §3.3, T-C-1-05)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_uow
from portfolio.api.routes.provision import provision_router
from portfolio.domain.entities.user import User
from portfolio.domain.enums import UserStatus
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

if TYPE_CHECKING:
    from fastapi.responses import Response
    from starlette.types import ASGIApp

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_BASE = "/internal/v1/users/provision"
_VALID_BODY = {"sub": "sub-test-001", "email": "test@example.com", "username": "tester"}


class _InjectRoleMiddleware(BaseHTTPMiddleware):
    """Test middleware that injects a ``role`` into request.state."""

    def __init__(self, app: ASGIApp, role: str) -> None:
        super().__init__(app)
        self._role = role

    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        request.state.role = self._role
        return await call_next(request)  # type: ignore[operator]


def _make_app(uow: FakeUnitOfWork, inject_role: str | None = None) -> FastAPI:
    app = FastAPI()

    if inject_role is not None:
        app.add_middleware(_InjectRoleMiddleware, role=inject_role)

    async def override_uow():  # type: ignore[return]
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.include_router(provision_router)
    return app


# ── Role gate ─────────────────────────────────────────────────────────────────


async def test_provision_endpoint_requires_system_role_no_role() -> None:
    """POST without any role in request.state → 401."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)  # no role injected

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json=_VALID_BODY)

    assert resp.status_code == 401


async def test_provision_endpoint_requires_system_role_wrong_role() -> None:
    """POST with role=user → 401 (only system allowed)."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="user")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json=_VALID_BODY)

    assert resp.status_code == 401


# ── Happy path ────────────────────────────────────────────────────────────────


async def test_provision_endpoint_creates_user() -> None:
    """POST with role=system → 200; user_id and tenant_id returned; created=True."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="system")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json=_VALID_BODY)

    assert resp.status_code == 200
    body = resp.json()
    assert "user_id" in body
    assert "tenant_id" in body
    assert body["email"] == "test@example.com"
    assert body["created"] is True
    assert body["linked"] is False


async def test_provision_endpoint_idempotent_returns_same_user() -> None:
    """Two calls with same sub → same user_id; second call has created=False."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="system")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post(_BASE, json=_VALID_BODY)
        resp2 = await client.post(_BASE, json=_VALID_BODY)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["user_id"] == resp2.json()["user_id"]
    assert resp2.json()["created"] is False


async def test_provision_endpoint_links_existing_user() -> None:
    """Existing user with no sub → 200 with linked=True."""
    uow = FakeUnitOfWork()
    existing = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="existing@example.com",
        status=UserStatus.ACTIVE,
        external_id=None,
    )
    uow.seed_user(existing)

    app = _make_app(uow, inject_role="system")
    body = {"sub": "sub-link", "email": "existing@example.com"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(existing.id)
    assert data["linked"] is True
    assert data["created"] is False


# ── Conflict ──────────────────────────────────────────────────────────────────


async def test_provision_endpoint_409_on_conflict() -> None:
    """Email already bound to a different sub → 409."""
    uow = FakeUnitOfWork()
    conflicting = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email="conflict@example.com",
        status=UserStatus.ACTIVE,
        external_id="sub-original",
    )
    uow.seed_user(conflicting)

    app = _make_app(uow, inject_role="system")
    conflict_body = {"sub": "sub-different", "email": "conflict@example.com"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json=conflict_body)

    assert resp.status_code == 409


# ── Validation ────────────────────────────────────────────────────────────────


async def test_provision_endpoint_rejects_invalid_email() -> None:
    """Non-email address in email field → 422."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="system")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json={"sub": "sub-x", "email": "not-an-email"})

    assert resp.status_code == 422


async def test_provision_endpoint_rejects_empty_sub() -> None:
    """Empty sub field → 422."""
    uow = FakeUnitOfWork()
    app = _make_app(uow, inject_role="system")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(_BASE, json={"sub": "", "email": "valid@example.com"})

    assert resp.status_code == 422
