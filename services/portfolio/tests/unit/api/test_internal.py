"""Unit tests for internal API endpoints (S10 -> S1).

Tests use FakeUnitOfWork with in-memory repositories.
Auth: InternalJWTMiddleware validates X-Internal-JWT (RS256) -- PRD-0025 Wave C.
F-CRIT-002: Routes now read tenant_id/user_id from request.state set by the JWT
middleware, not from headers or query strings. Test middleware injects these values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow, get_uow
from portfolio.api.internal import internal_router
from portfolio.domain.entities.user import User
from portfolio.domain.entities.watchlist import Watchlist
from portfolio.domain.entities.watchlist_member import WatchlistMember
from portfolio.domain.enums import WatchlistStatus
from starlette.middleware.base import BaseHTTPMiddleware

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _InjectStateMiddleware(BaseHTTPMiddleware):
    """Test-only middleware that sets request.state.tenant_id and user_id.

    Simulates what InternalJWTMiddleware does in production after decoding the JWT.
    """

    def __init__(self, app: Any, tenant_id: UUID | None = None, user_id: UUID | None = None) -> None:
        super().__init__(app)
        self._tenant_id = tenant_id
        self._user_id = user_id

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        if self._tenant_id is not None:
            request.state.tenant_id = str(self._tenant_id)
        if self._user_id is not None:
            request.state.user_id = str(self._user_id)
        return await call_next(request)


def _make_app(
    uow: FakeUnitOfWork,
    *,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with only the internal router."""
    app = FastAPI()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_read_uow] = override_uow  # same fake for read
    app.include_router(internal_router)

    if tenant_id is not None or user_id is not None:
        app.add_middleware(_InjectStateMiddleware, tenant_id=tenant_id, user_id=user_id)

    return app


def _seed_watchlist_data(uow: FakeUnitOfWork) -> tuple:
    """Seed a tenant, user, watchlist, and member. Returns (tenant_id, user_id, watchlist_id, entity_id)."""
    tenant_id = uuid4()
    user_id = uuid4()
    watchlist_id = uuid4()
    entity_id = uuid4()

    watchlist = Watchlist(
        id=watchlist_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name="My Watchlist",
        status=WatchlistStatus.ACTIVE,
        created_at=datetime.now(tz=UTC),
    )
    uow._watchlists._store[watchlist_id] = watchlist

    member = WatchlistMember(
        id=uuid4(),
        watchlist_id=watchlist_id,
        entity_id=entity_id,
        entity_type="company",
        added_at=datetime.now(tz=UTC),
    )
    uow._watchlist_members._store[(watchlist_id, entity_id)] = member

    return tenant_id, user_id, watchlist_id, entity_id


# -- Health ----------------------------------------------------------------


async def test_internal_health() -> None:
    """GET /internal/v1/health returns 200 with no auth required."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/internal/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


# -- Single entity lookup ---------------------------------------------------


async def test_by_entity_returns_watchers() -> None:
    """GET /internal/v1/watchlists/by-entity/{entity_id} returns watcher list."""
    uow = FakeUnitOfWork()
    _, user_id, watchlist_id, entity_id = _seed_watchlist_data(uow)
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/watchlists/by-entity/{entity_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_id"] == str(entity_id)
    assert len(data["watchers"]) == 1
    assert data["watchers"][0]["user_id"] == str(user_id)
    assert data["watchers"][0]["watchlist_id"] == str(watchlist_id)


async def test_by_entity_empty() -> None:
    """Unknown entity -> empty watchers array."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/watchlists/by-entity/{uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["watchers"] == []


# -- Batch lookup -----------------------------------------------------------


async def test_by_entities_batch() -> None:
    """POST /internal/v1/watchlists/by-entities returns correct map."""
    uow = FakeUnitOfWork()
    _, user_id, _watchlist_id, entity_id = _seed_watchlist_data(uow)
    unknown_id = uuid4()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/watchlists/by-entities",
            json={"entity_ids": [str(entity_id), str(unknown_id)]},
        )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results[str(entity_id)]) == 1
    assert results[str(entity_id)][0]["user_id"] == str(user_id)
    assert results[str(unknown_id)] == []


async def test_by_entities_max_100() -> None:
    """> 100 entity_ids -> 400 error."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    ids = [str(uuid4()) for _ in range(101)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/watchlists/by-entities",
            json={"entity_ids": ids},
        )
    assert resp.status_code == 400


# -- Watchlist entities -----------------------------------------------------


async def test_watchlist_entities_list() -> None:
    """GET /internal/v1/watchlists/{watchlist_id}/entities returns entity_ids."""
    uow = FakeUnitOfWork()
    _, _, watchlist_id, entity_id = _seed_watchlist_data(uow)
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/watchlists/{watchlist_id}/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["watchlist_id"] == str(watchlist_id)
    assert str(entity_id) in data["entity_ids"]


# -- GET /internal/v1/users/{user_id} --------------------------------------


def _seed_user(uow: FakeUnitOfWork) -> tuple:
    """Seed a user for email digest tests. Returns (tenant_id, user_id, email)."""
    tenant_id = uuid4()
    user_id = uuid4()
    email = "alice@example.com"
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=email,
        created_at=datetime.now(tz=UTC),
    )
    uow._users._store[user_id] = user
    return tenant_id, user_id, email


async def test_get_user_for_digest_returns_email() -> None:
    """GET /internal/v1/users/{user_id} returns email_address for digest delivery."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, email = _seed_user(uow)
    app = _make_app(uow, tenant_id=tenant_id, user_id=user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(user_id)
    assert data["tenant_id"] == str(tenant_id)
    assert data["email_address"] == email
    assert "created_at" in data


async def test_get_user_for_digest_404_unknown_user() -> None:
    """Unknown user_id -> 404."""
    uow = FakeUnitOfWork()
    tenant_id = uuid4()
    unknown_id = uuid4()
    app = _make_app(uow, tenant_id=tenant_id, user_id=unknown_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{unknown_id}")
    assert resp.status_code == 404


async def test_get_user_for_digest_404_wrong_tenant() -> None:
    """User in tenant A is not visible to tenant B -> 404."""
    uow = FakeUnitOfWork()
    _tenant_id, user_id, _ = _seed_user(uow)
    other_tenant = uuid4()
    app = _make_app(uow, tenant_id=other_tenant, user_id=user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}")
    assert resp.status_code == 404


async def test_get_user_for_digest_response_shape() -> None:
    """Response contains exactly: user_id, tenant_id, email_address, username, created_at."""
    uow = FakeUnitOfWork()
    tenant_id, user_id, _email = _seed_user(uow)
    app = _make_app(uow, tenant_id=tenant_id, user_id=user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    expected_keys = {"user_id", "tenant_id", "email_address", "username", "created_at"}
    assert set(data.keys()) == expected_keys
