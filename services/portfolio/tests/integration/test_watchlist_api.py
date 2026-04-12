"""Integration tests for watchlist API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.app import create_app
from portfolio.application.ports.cache import NoOpWatchlistCache

from tests.integration.helpers import make_tenant, make_user

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
async def watchlist_client(postgres_container: str) -> AsyncGenerator[AsyncClient, None]:
    """Like integration_client but also overrides WatchlistCacheDep with NoOp."""
    from portfolio.api.dependencies import get_uow, get_watchlist_cache
    from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(postgres_container, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_uow() -> AsyncGenerator:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            yield uow

    app = create_app()
    app.dependency_overrides[get_uow] = _test_uow
    app.dependency_overrides[get_watchlist_cache] = lambda: NoOpWatchlistCache()
    app.state.session_factory = session_factory
    app.state.engine = engine

    from tests.integration.helpers import _INTERNAL_HEADERS

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────────────


async def make_watchlist(
    client: AsyncClient,
    tenant_id: str,
    owner_id: str,
    name: str = "My Watchlist",
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/watchlists",
        json={"name": name},
        headers={"X-Tenant-ID": tenant_id, "X-Owner-ID": owner_id},
    )
    assert resp.status_code == 201, f"make_watchlist failed: {resp.text}"
    return resp.json()


async def make_member(
    client: AsyncClient,
    tenant_id: str,
    owner_id: str,
    watchlist_id: str,
    entity_id: str | None = None,
    entity_type: str = "company",
) -> dict[str, Any]:
    if entity_id is None:
        entity_id = str(uuid4())
    resp = await client.post(
        f"/api/v1/watchlists/{watchlist_id}/members",
        json={"entity_id": entity_id, "entity_type": entity_type},
        headers={"X-Tenant-ID": tenant_id, "X-Owner-ID": owner_id},
    )
    assert resp.status_code == 201, f"make_member failed: {resp.text}"
    return resp.json()


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_create_watchlist_returns_201(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client)
    user = await make_user(watchlist_client, tenant["id"])

    resp = await watchlist_client.post(
        "/api/v1/watchlists",
        json={"name": "Tech Giants"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Tech Giants"
    assert data["status"] == "active"
    assert data["user_id"] == user["id"]


async def test_create_watchlist_duplicate_name_returns_409(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="DupTenant")
    user = await make_user(watchlist_client, tenant["id"], email="dup@test.com")
    await make_watchlist(watchlist_client, tenant["id"], user["id"], name="DupList")

    resp = await watchlist_client.post(
        "/api/v1/watchlists",
        json={"name": "DupList"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 409


async def test_list_watchlists_returns_user_watchlists_only(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="ListTenant")
    user1 = await make_user(watchlist_client, tenant["id"], email="user1@list.com")
    user2 = await make_user(watchlist_client, tenant["id"], email="user2@list.com")

    await make_watchlist(watchlist_client, tenant["id"], user1["id"], name="User1 WL")
    await make_watchlist(watchlist_client, tenant["id"], user2["id"], name="User2 WL")

    resp = await watchlist_client.get(
        "/api/v1/watchlists",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user1["id"]},
    )
    assert resp.status_code == 200
    names = [w["name"] for w in resp.json()]
    assert "User1 WL" in names
    assert "User2 WL" not in names


async def test_get_watchlist_returns_200(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="GetTenant")
    user = await make_user(watchlist_client, tenant["id"], email="get@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])

    resp = await watchlist_client.get(
        f"/api/v1/watchlists/{wl['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == wl["id"]


async def test_get_watchlist_not_found_returns_404(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="NotFoundTenant")
    user = await make_user(watchlist_client, tenant["id"], email="nf@test.com")

    resp = await watchlist_client.get(
        f"/api/v1/watchlists/{uuid4()}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 404


async def test_get_watchlist_wrong_owner_returns_403(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="AuthTenant")
    owner = await make_user(watchlist_client, tenant["id"], email="owner@auth.com")
    other = await make_user(watchlist_client, tenant["id"], email="other@auth.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], owner["id"])

    resp = await watchlist_client.get(
        f"/api/v1/watchlists/{wl['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": other["id"]},
    )
    assert resp.status_code == 403


async def test_delete_watchlist_returns_204(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="DelTenant")
    user = await make_user(watchlist_client, tenant["id"], email="del@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])

    resp = await watchlist_client.delete(
        f"/api/v1/watchlists/{wl['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 204


async def test_add_member_returns_201(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="MemberTenant")
    user = await make_user(watchlist_client, tenant["id"], email="member@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])
    entity_id = str(uuid4())

    resp = await watchlist_client.post(
        f"/api/v1/watchlists/{wl['id']}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_id"] == entity_id
    assert data["entity_type"] == "company"


async def test_add_member_duplicate_returns_409(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="DupMemberTenant")
    user = await make_user(watchlist_client, tenant["id"], email="dupmember@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])
    entity_id = str(uuid4())

    await make_member(watchlist_client, tenant["id"], user["id"], wl["id"], entity_id)

    resp = await watchlist_client.post(
        f"/api/v1/watchlists/{wl['id']}/members",
        json={"entity_id": entity_id, "entity_type": "company"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 409


async def test_remove_member_returns_204(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="RemoveTenant")
    user = await make_user(watchlist_client, tenant["id"], email="remove@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])
    entity_id = str(uuid4())

    await make_member(watchlist_client, tenant["id"], user["id"], wl["id"], entity_id)

    resp = await watchlist_client.delete(
        f"/api/v1/watchlists/{wl['id']}/members/{entity_id}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 204


async def test_remove_member_not_found_returns_404(watchlist_client: AsyncClient) -> None:
    tenant = await make_tenant(watchlist_client, name="RemoveNFTenant")
    user = await make_user(watchlist_client, tenant["id"], email="removenf@test.com")
    wl = await make_watchlist(watchlist_client, tenant["id"], user["id"])

    resp = await watchlist_client.delete(
        f"/api/v1/watchlists/{wl['id']}/members/{uuid4()}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 404
