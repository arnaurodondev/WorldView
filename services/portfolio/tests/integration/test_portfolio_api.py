"""Integration tests for portfolio API endpoints."""

from __future__ import annotations

import uuid

import pytest

from tests.integration.helpers import OutboxAssertions, make_portfolio, make_tenant, make_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_portfolio_happy_path(integration_client, db_session) -> None:
    """POST /api/v1/portfolios creates a portfolio record."""
    tenant = await make_tenant(integration_client, name="PortCo")
    user = await make_user(integration_client, tenant["id"])
    tenant_id = tenant["id"]
    user_id = user["id"]

    resp = await integration_client.post(
        "/api/v1/portfolios",
        json={"name": "Growth Fund", "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Growth Fund"
    assert data["currency"] == "USD"
    assert data["owner_id"] == user_id

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.created")


async def test_list_portfolios_scoped_to_owner(integration_client) -> None:
    """GET /api/v1/portfolios returns only portfolios for the given owner."""
    tenant = await make_tenant(integration_client, name="ListCo")
    user1 = await make_user(integration_client, tenant["id"], email="owner1@listco.com")
    user2 = await make_user(integration_client, tenant["id"], email="owner2@listco.com")
    tenant_id = tenant["id"]

    # Create portfolio for user1
    await make_portfolio(integration_client, tenant_id, user1["id"], name="P1")
    # Create portfolio for user2
    await make_portfolio(integration_client, tenant_id, user2["id"], name="P2")

    # List as user1 — should see only P1
    resp = await integration_client.get(
        "/api/v1/portfolios",
        headers={"X-Tenant-ID": tenant_id, "X-Owner-ID": user1["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "P1"


async def test_get_portfolio_happy_path(integration_client) -> None:
    """GET /api/v1/portfolios/{id} returns the portfolio."""
    tenant = await make_tenant(integration_client, name="GetPortCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])

    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == portfolio["id"]


async def test_get_portfolio_cross_tenant_denied(integration_client) -> None:
    """GET /api/v1/portfolios/{id} with wrong tenant_id returns 403/404."""
    tenant1 = await make_tenant(integration_client, name="Tenant1")
    tenant2 = await make_tenant(integration_client, name="Tenant2")
    user = await make_user(integration_client, tenant1["id"])
    portfolio = await make_portfolio(integration_client, tenant1["id"], user["id"])

    # Try to access tenant1's portfolio using tenant2's ID
    resp = await integration_client.get(
        f"/api/v1/portfolios/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant2["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code in (403, 404), f"Expected 403/404, got {resp.status_code}"


async def test_rename_portfolio(integration_client, db_session) -> None:
    """PUT /api/v1/portfolios/{id} renames the portfolio."""
    tenant = await make_tenant(integration_client, name="RenameCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"], name="Old Name")

    resp = await integration_client.put(
        f"/api/v1/portfolios/{portfolio['id']}",
        json={"name": "New Name"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.renamed")


async def test_rename_portfolio_wrong_owner_denied(integration_client) -> None:
    """PUT /api/v1/portfolios/{id} by wrong owner returns 403."""
    tenant = await make_tenant(integration_client, name="AuthCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])
    other_user = str(uuid.uuid4())

    resp = await integration_client.put(
        f"/api/v1/portfolios/{portfolio['id']}",
        json={"name": "Hacked"},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": other_user},
    )
    assert resp.status_code == 403


async def test_archive_portfolio(integration_client, db_session) -> None:
    """DELETE /api/v1/portfolios/{id} archives the portfolio (204)."""
    tenant = await make_tenant(integration_client, name="ArchiveCo")
    user = await make_user(integration_client, tenant["id"])
    portfolio = await make_portfolio(integration_client, tenant["id"], user["id"])

    resp = await integration_client.delete(
        f"/api/v1/portfolios/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 204

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "portfolio.archived")
