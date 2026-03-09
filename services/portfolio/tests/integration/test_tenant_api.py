"""Integration tests for tenant API endpoints."""

from __future__ import annotations

import pytest
from tests.integration.helpers import OutboxAssertions, make_tenant

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_create_tenant_creates_record(integration_client, db_session) -> None:
    """POST /api/v1/tenants creates a tenant record in the DB."""
    resp = await integration_client.post("/api/v1/tenants", json={"name": "ACME Corp"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "ACME Corp"
    assert data["status"] == "active"
    assert "id" in data


async def test_create_tenant_emits_outbox_event(integration_client, db_session) -> None:
    """POST /api/v1/tenants emits a tenant.created outbox event."""
    resp = await integration_client.post("/api/v1/tenants", json={"name": "OutboxCo"})
    assert resp.status_code == 201

    await OutboxAssertions.assert_event_type_in_outbox(db_session, "tenant.created")


async def test_get_tenant_returns_correct_data(integration_client, db_session) -> None:
    """GET /api/v1/tenants/{id} returns the correct tenant data."""
    tenant = await make_tenant(integration_client, name="GetMe Corp")
    tenant_id = tenant["id"]

    resp = await integration_client.get(f"/api/v1/tenants/{tenant_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == tenant_id
    assert data["name"] == "GetMe Corp"


async def test_get_tenant_not_found(integration_client) -> None:
    """GET /api/v1/tenants/{id} returns 404 for unknown tenant."""
    import uuid

    resp = await integration_client.get(f"/api/v1/tenants/{uuid.uuid4()}")
    assert resp.status_code == 404
