"""Integration tests for alert preferences API endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.integration.helpers import make_tenant, make_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_get_alert_preferences_returns_200_with_defaults(integration_client) -> None:
    """GET /alert-preferences returns 200 with all alert types defaulting to enabled."""
    tenant = await make_tenant(integration_client, name="APTenant1")
    user = await make_user(integration_client, tenant["id"], email="ap1@test.com")

    resp = await integration_client.get(
        "/api/v1/alert-preferences",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "preferences" in data
    assert "suppressions" in data
    assert len(data["preferences"]) == 4  # 4 AlertType values
    for pref in data["preferences"]:
        assert pref["enabled"] is True  # default


async def test_put_preference_returns_200(integration_client) -> None:
    """PUT /alert-preferences/{alert_type} updates the preference."""
    tenant = await make_tenant(integration_client, name="APTenant2")
    user = await make_user(integration_client, tenant["id"], email="ap2@test.com")

    resp = await integration_client.put(
        "/api/v1/alert-preferences/signal",
        json={"enabled": False},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["alert_type"] == "signal"
    assert data["enabled"] is False


async def test_put_invalid_alert_type_returns_422(integration_client) -> None:
    """PUT /alert-preferences/{alert_type} with unknown type returns 422."""
    tenant = await make_tenant(integration_client, name="APTenant3")
    user = await make_user(integration_client, tenant["id"], email="ap3@test.com")

    resp = await integration_client.put(
        "/api/v1/alert-preferences/not_a_type",
        json={"enabled": False},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 422


async def test_post_suppression_returns_201(integration_client) -> None:
    """POST /alert-preferences/suppressions creates entity suppression."""
    tenant = await make_tenant(integration_client, name="APTenant4")
    user = await make_user(integration_client, tenant["id"], email="ap4@test.com")
    entity_id = str(uuid4())

    resp = await integration_client.post(
        "/api/v1/alert-preferences/suppressions",
        json={"entity_id": entity_id},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_id"] == entity_id


async def test_delete_suppression_returns_204(integration_client) -> None:
    """DELETE /alert-preferences/suppressions/{entity_id} removes suppression."""
    tenant = await make_tenant(integration_client, name="APTenant5")
    user = await make_user(integration_client, tenant["id"], email="ap5@test.com")
    entity_id = str(uuid4())

    # Create first
    await integration_client.post(
        "/api/v1/alert-preferences/suppressions",
        json={"entity_id": entity_id},
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )

    resp = await integration_client.delete(
        f"/api/v1/alert-preferences/suppressions/{entity_id}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 204


async def test_delete_suppression_not_found_returns_404(integration_client) -> None:
    """DELETE /alert-preferences/suppressions/{entity_id} for missing entity → 404."""
    tenant = await make_tenant(integration_client, name="APTenant6")
    user = await make_user(integration_client, tenant["id"], email="ap6@test.com")

    resp = await integration_client.delete(
        f"/api/v1/alert-preferences/suppressions/{uuid4()}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 404
