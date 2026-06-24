"""Integration tests for portfolio API endpoints.

After PLAN-0025, all routes read tenant_id and user_id from request.state (set
by InternalJWTMiddleware from the X-Internal-JWT header).  The old X-Tenant-ID
and X-Owner-ID headers are completely ignored.

The integration_client fixture pre-seeds INTEGRATION_TENANT_ID / USER_ID in the
DB so that use cases that validate tenant/user existence find valid rows.  Tests
that need a second identity (cross-user or cross-tenant isolation) seed them
directly via seed_tenant() / seed_user() and inject a per-request JWT via
make_jwt_headers().
"""

from __future__ import annotations

import pytest
from tests.integration.helpers import (
    INTEGRATION_TENANT2_ID,
    INTEGRATION_TENANT_ID,
    INTEGRATION_USER2_ID,
    INTEGRATION_USER3_ID,
    INTEGRATION_USER_ID,
    OutboxAssertions,
    make_jwt_headers,
    seed_tenant,
    seed_user,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_portfolio_happy_path(integration_client, db_session) -> None:
    """POST /api/v1/portfolios creates a portfolio record."""
    # INTEGRATION_TENANT_ID + INTEGRATION_USER_ID are seeded by integration_client.
    # Routes read tenant_id/user_id from JWT state — X-Tenant-ID header is ignored.
    resp = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "Growth Fund", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Growth Fund"
    assert data["currency"] == "USD"
    assert data["owner_id"] == INTEGRATION_USER_ID

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.created")


async def test_list_portfolios_scoped_to_owner(integration_client, db_session) -> None:
    """GET /api/v1/portfolios returns only portfolios owned by the requesting user."""
    # Seed user2 under the same tenant so CreatePortfolioUseCase finds a valid user row.
    await seed_user(db_session, INTEGRATION_USER2_ID, INTEGRATION_TENANT_ID, "user2-portlist@test.com")

    # Create portfolio as user1 (default JWT carries INTEGRATION_USER_ID).
    r1 = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "P1 Scoped", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r1.status_code == 201

    # Create portfolio as user2 using a per-request JWT that carries user2's identity.
    user2_headers = make_jwt_headers(INTEGRATION_TENANT_ID, INTEGRATION_USER2_ID)
    r2 = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "P2 Scoped", "owner_user_id": INTEGRATION_USER2_ID, "currency": "USD"},
        headers=user2_headers,
    )
    assert r2.status_code == 201

    # List as user1 (default JWT) — must include P1 and exclude P2.
    resp = await integration_client.get("/api/v1/portfolios")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["items"]]
    assert "P1 Scoped" in names
    assert "P2 Scoped" not in names


async def test_get_portfolio_happy_path(integration_client) -> None:
    """GET /api/v1/portfolios/{id} returns the portfolio."""
    r = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "GetPortfolio", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["id"]

    resp = await integration_client.get(f"/api/v1/portfolios/{portfolio_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == portfolio_id


async def test_get_portfolio_cross_tenant_denied(integration_client, db_session) -> None:
    """GET /api/v1/portfolios/{id} with a different tenant_id returns 403 or 404."""
    # Seed tenant2 and a user under it so the JWT identity is resolvable in the DB.
    await seed_tenant(db_session, INTEGRATION_TENANT2_ID, "Tenant Two")
    await seed_user(db_session, INTEGRATION_USER3_ID, INTEGRATION_TENANT2_ID, "user3-cross@t2.com")

    # Create portfolio under tenant1 (INTEGRATION_TENANT_ID, via default JWT).
    r = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "T1 Portfolio", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["id"]

    # Tenant2 user attempts to access tenant1's portfolio — must be denied.
    tenant2_headers = make_jwt_headers(INTEGRATION_TENANT2_ID, INTEGRATION_USER3_ID)
    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio_id}",
        headers=tenant2_headers,
    )
    assert resp.status_code in (
        403,
        404,
    ), f"Expected 403/404 for cross-tenant access, got {resp.status_code}: {resp.text}"


async def test_rename_portfolio(integration_client, db_session) -> None:
    """PUT /api/v1/portfolios/{id} renames the portfolio."""
    r = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "Old Name Portfolio", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["id"]

    resp = await integration_client.put(
        f"/api/v1/portfolios/{portfolio_id}",
        json={"name": "New Name Portfolio"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name Portfolio"

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.renamed")


async def test_rename_portfolio_wrong_owner_denied(integration_client, db_session) -> None:
    """PUT /api/v1/portfolios/{id} by a different user returns 403."""
    # Seed user2 to act as the "wrong owner".
    await seed_user(db_session, INTEGRATION_USER2_ID, INTEGRATION_TENANT_ID, "user2-rename@test.com")

    # Create portfolio as user1 (default JWT).
    r = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "AuthPortfolio", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["id"]

    # user2 attempts to rename — must be rejected (403 Forbidden).
    user2_headers = make_jwt_headers(INTEGRATION_TENANT_ID, INTEGRATION_USER2_ID)
    resp = await integration_client.put(
        f"/api/v1/portfolios/{portfolio_id}",
        json={"name": "Hacked"},
        headers=user2_headers,
    )
    assert resp.status_code == 403


async def test_archive_portfolio(integration_client, db_session) -> None:
    """DELETE /api/v1/portfolios/{id} archives the portfolio (204)."""
    r = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "Archive Me", "owner_user_id": INTEGRATION_USER_ID, "currency": "USD"},
    )
    assert r.status_code == 201
    portfolio_id = r.json()["id"]

    resp = await integration_client.delete(f"/api/v1/portfolios/{portfolio_id}")
    assert resp.status_code == 204

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.archived")
