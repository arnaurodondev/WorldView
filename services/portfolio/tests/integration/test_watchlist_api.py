"""Integration tests for watchlist API endpoints.

After PLAN-0025, routes read tenant_id / user_id from request.state (JWT state).
X-Tenant-ID and X-Owner-ID headers are ignored.

All watchlists created here belong to INTEGRATION_USER_ID (from the JWT embedded
in watchlist_client).  To avoid WATCHLIST_ALREADY_EXISTS collisions across tests
sharing the session-scoped DB, every test generates a unique watchlist name via
uuid4().  Isolation tests (cross-user ownership) seed a second user and inject
a per-request JWT via make_jwt_headers().
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.app import create_app
from portfolio.application.ports.cache import NoOpWatchlistCache

from tests.integration.helpers import (
    INTEGRATION_TENANT_ID,
    INTEGRATION_USER2_ID,
    INTEGRATION_USER_ID,
    make_jwt_headers,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
async def watchlist_client(postgres_container: str) -> AsyncGenerator[AsyncClient, None]:
    """Like integration_client but also overrides WatchlistCacheDep with NoOp.

    Seeds INTEGRATION_TENANT_ID and INTEGRATION_USER_ID so that CreateWatchlistUseCase
    (which validates user existence via uow.users.get()) finds valid rows regardless
    of test execution order.
    """
    import os

    from portfolio.api.dependencies import get_uow, get_watchlist_cache
    from portfolio.infrastructure.db.models.tenant import TenantModel
    from portfolio.infrastructure.db.models.user import UserModel
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from tests.integration.helpers import _INTERNAL_HEADERS

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Seed the integration identity so watchlist use cases can resolve the user.
    async with session_factory() as session:
        await session.merge(TenantModel(id=UUID(INTEGRATION_TENANT_ID), name="Integration Tenant"))
        await session.merge(
            UserModel(
                id=UUID(INTEGRATION_USER_ID),
                tenant_id=UUID(INTEGRATION_TENANT_ID),
                email="integration@test.com",
            )
        )
        await session.commit()

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    os.environ["PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION"] = "true"
    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.dependency_overrides[get_watchlist_cache] = lambda: NoOpWatchlistCache()
    app.state.session_factory = session_factory
    app.state.engine = engine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
    os.environ.pop("PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION", None)


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_create_watchlist_returns_201(watchlist_client: AsyncClient) -> None:
    # Use a unique name to avoid WATCHLIST_ALREADY_EXISTS with the session-scoped DB.
    unique_name = f"Tech Giants {uuid4().hex[:8]}"
    resp = await watchlist_client.post(
        "/api/v1/watchlists",
        json={"name": unique_name},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == unique_name
    assert data["status"] == "active"
    # Routes set user_id from JWT state, not from request headers.
    assert data["user_id"] == INTEGRATION_USER_ID


async def test_create_watchlist_duplicate_name_returns_409(watchlist_client: AsyncClient) -> None:
    unique_name = f"DupList {uuid4().hex[:8]}"
    await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})

    resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert resp.status_code == 409


async def test_list_watchlists_returns_user_watchlists_only(watchlist_client, db_session) -> None:
    """GET /api/v1/watchlists returns only the watchlists belonging to the caller."""
    # Seed user2 so CreateWatchlistUseCase can validate user existence.
    await seed_user(db_session, INTEGRATION_USER2_ID, INTEGRATION_TENANT_ID, "user2-wl-list@test.com")

    suffix = uuid4().hex[:8]
    wl1_name = f"User1 WL {suffix}"
    wl2_name = f"User2 WL {suffix}"

    # Create watchlist as user1 (default JWT).
    r1 = await watchlist_client.post("/api/v1/watchlists", json={"name": wl1_name})
    assert r1.status_code == 201

    # Create watchlist as user2 (per-request JWT with user2 identity).
    user2_headers = make_jwt_headers(INTEGRATION_TENANT_ID, INTEGRATION_USER2_ID)
    r2 = await watchlist_client.post(
        "/api/v1/watchlists",
        json={"name": wl2_name},
        headers=user2_headers,
    )
    assert r2.status_code == 201

    # List as user1 — must include wl1 and exclude wl2.
    resp = await watchlist_client.get("/api/v1/watchlists")
    assert resp.status_code == 200
    names = [w["name"] for w in resp.json()]
    assert wl1_name in names
    assert wl2_name not in names


async def test_get_watchlist_returns_200(watchlist_client: AsyncClient) -> None:
    unique_name = f"GetWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    resp = await watchlist_client.get(f"/api/v1/watchlists/{wl_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == wl_id


async def test_get_watchlist_not_found_returns_404(watchlist_client: AsyncClient) -> None:
    resp = await watchlist_client.get(f"/api/v1/watchlists/{uuid4()}")
    assert resp.status_code == 404


async def test_get_watchlist_wrong_owner_returns_403(watchlist_client, db_session) -> None:
    """GET /api/v1/watchlists/{id} by a different user returns 403."""
    # Seed user2 to act as the "wrong owner".
    await seed_user(db_session, INTEGRATION_USER2_ID, INTEGRATION_TENANT_ID, "user2-wl-auth@test.com")

    # Create watchlist as user1 (default JWT).
    unique_name = f"AuthWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    # user2 attempts to access user1's watchlist — must be rejected.
    user2_headers = make_jwt_headers(INTEGRATION_TENANT_ID, INTEGRATION_USER2_ID)
    resp = await watchlist_client.get(f"/api/v1/watchlists/{wl_id}", headers=user2_headers)
    assert resp.status_code == 403


async def test_delete_watchlist_returns_204(watchlist_client: AsyncClient) -> None:
    unique_name = f"DelWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    resp = await watchlist_client.delete(f"/api/v1/watchlists/{wl_id}")
    assert resp.status_code == 204


async def test_add_member_returns_201(watchlist_client: AsyncClient) -> None:
    unique_name = f"MemberWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    entity_id = str(uuid4())
    resp = await watchlist_client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_id"] == entity_id
    assert data["entity_type"] == "company"


async def test_add_member_duplicate_returns_409(watchlist_client: AsyncClient) -> None:
    unique_name = f"DupMemberWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    entity_id = str(uuid4())
    await watchlist_client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
    )

    resp = await watchlist_client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
    )
    assert resp.status_code == 409


async def test_remove_member_returns_204(watchlist_client: AsyncClient) -> None:
    unique_name = f"RemoveWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    entity_id = str(uuid4())
    await watchlist_client.post(
        f"/api/v1/watchlists/{wl_id}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
    )

    resp = await watchlist_client.delete(f"/api/v1/watchlists/{wl_id}/members/{entity_id}")
    assert resp.status_code == 204


async def test_remove_member_not_found_returns_404(watchlist_client: AsyncClient) -> None:
    unique_name = f"RemoveNFWL {uuid4().hex[:8]}"
    create_resp = await watchlist_client.post("/api/v1/watchlists", json={"name": unique_name})
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    resp = await watchlist_client.delete(f"/api/v1/watchlists/{wl_id}/members/{uuid4()}")
    assert resp.status_code == 404
