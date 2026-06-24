"""Integration tests for user API endpoints."""

from __future__ import annotations

import pytest
from tests.integration.helpers import OutboxAssertions, make_tenant, make_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_user_happy_path(integration_client, db_session) -> None:
    """POST /api/v1/users creates a user under an active tenant."""
    tenant = await make_tenant(integration_client, name="UserCo")
    tenant_id = tenant["id"]

    resp = await integration_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": "alice@userco.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@userco.com"
    assert data["tenant_id"] == tenant_id
    assert data["status"] == "active"


async def test_create_user_emits_outbox_event(integration_client, db_session) -> None:
    """POST /api/v1/users emits a user.created outbox event."""
    tenant = await make_tenant(integration_client, name="EventCo")
    await integration_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant["id"], "email": "bob@eventco.com"},
    )
    await OutboxAssertions.assert_event_type_in_outbox(db_session, "user.created")


async def test_create_user_duplicate_email_returns_409(integration_client) -> None:
    """POST /api/v1/users returns 409 on duplicate email within same tenant."""
    tenant = await make_tenant(integration_client, name="DupCo")
    tenant_id = tenant["id"]

    await make_user(integration_client, tenant_id, email="dup@dupco.com")

    resp = await integration_client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": "dup@dupco.com"},
    )
    assert resp.status_code == 409


async def test_get_user_happy_path(integration_client) -> None:
    """GET /api/v1/users/{id} returns the user.

    The GET /users/{id} route reads tenant_id from JWT state (INTEGRATION_TENANT_ID).
    The user must be created under that same tenant_id so uow.users.get() finds it.
    """
    from tests.integration.helpers import INTEGRATION_TENANT_ID

    # Create the user under INTEGRATION_TENANT_ID (passed as body, not JWT).
    # The GET route will look up with tenant_id=INTEGRATION_TENANT_ID from JWT state.
    resp_create = await integration_client.post(
        "/api/v1/users",
        json={"tenant_id": INTEGRATION_TENANT_ID, "email": "charlie@test.com"},
    )
    assert resp_create.status_code == 201
    user_id = resp_create.json()["id"]

    resp = await integration_client.get(f"/api/v1/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "charlie@test.com"


async def test_get_user_not_found(integration_client) -> None:
    """GET /api/v1/users/{id} returns 404 for unknown user."""
    import uuid

    tenant = await make_tenant(integration_client)
    resp = await integration_client.get(
        f"/api/v1/users/{uuid.uuid4()}",
        headers={"X-Tenant-ID": tenant["id"]},
    )
    assert resp.status_code == 404
