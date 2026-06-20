"""Integration tests for the S10 /api/v1/alert-rules CRUD routes (PLAN-0113 T-1-05).

Drives the full ASGI stack (InternalJWTMiddleware → route → use case → repo →
testcontainer DB). Requires Docker (skipped otherwise).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def rules_client(integration_app, db_session_factory):  # type: ignore[no-untyped-def]
    """integration_app with the read_factory pointed at the testcontainer too.

    The read CRUD use cases use ``read_factory``; create_app wired it to the
    (unconnected) default engine, so we repoint it at the test DB factory.
    """
    factory, _engine = db_session_factory
    integration_app.state.read_factory = factory
    return integration_app


# Tenant + user injected via the JWT (the route's TenantUserDep needs both).
_TENANT_ID = "00000000-0000-0000-0000-0000000000aa"
_USER_ID = "00000000-0000-0000-0000-0000000000bb"


def _rule_owner_jwt() -> str:
    """HS256 JWT carrying a valid tenant_id + user_id (decoded unverified in tests)."""
    import time

    import jwt as _jwt

    payload = {
        "iss": "worldview-gateway",
        "sub": _USER_ID,
        "tenant_id": _TENANT_ID,
        "role": "user",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "integration-test-secret", algorithm="HS256")


@pytest.fixture
async def client(rules_client):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    headers = {"X-Internal-JWT": _rule_owner_jwt()}
    transport = ASGITransport(app=rules_client)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c


def _price_body() -> dict:  # type: ignore[type-arg]
    return {
        "rule_type": "PRICE_CROSS",
        "name": "AAPL > 200",
        "condition": {"instrument_id": str(uuid4()), "operator": "above", "value": 200.0},
        "severity": "high",
    }


@pytest.mark.asyncio
async def test_create_list_get_delete_rule(client) -> None:  # type: ignore[no-untyped-def]
    # Create
    resp = await client.post("/api/v1/alert-rules", json=_price_body())
    assert resp.status_code == 201, resp.text
    created = resp.json()
    rule_id = created["rule_id"]
    assert created["rule_type"] == "PRICE_CROSS"
    assert created["entity_id"] is not None
    assert created["last_state"] is None

    # List
    resp = await client.get("/api/v1/alert-rules")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["rule_id"] == rule_id

    # Get
    resp = await client.get(f"/api/v1/alert-rules/{rule_id}")
    assert resp.status_code == 200

    # Delete
    resp = await client.delete(f"/api/v1/alert-rules/{rule_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/alert-rules/{rule_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_bad_condition_returns_400(client) -> None:  # type: ignore[no-untyped-def]
    body = _price_body()
    body["condition"] = {"instrument_id": str(uuid4()), "operator": "above", "value": -5}
    resp = await client.post("/api/v1/alert-rules", json=body)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_kg_equal_nodes_returns_422(client) -> None:  # type: ignore[no-untyped-def]
    node = str(uuid4())
    body = {
        "rule_type": "KG_CONNECTION",
        "name": "self loop",
        "condition": {"source_entity_id": node, "target_entity_id": node, "max_hops": 2},
    }
    resp = await client.post("/api/v1/alert-rules", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_condition_rearms(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/alert-rules", json=_price_body())
    rule_id = resp.json()["rule_id"]

    new_iid = str(uuid4())
    patch = {"condition": {"instrument_id": new_iid, "operator": "below", "value": 50.0}}
    resp = await client.patch(f"/api/v1/alert-rules/{rule_id}", json=patch)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["condition"]["value"] == 50.0
    assert updated["last_state"] is None


@pytest.mark.asyncio
async def test_unknown_rule_type_returns_400(client) -> None:  # type: ignore[no-untyped-def]
    body = _price_body()
    body["rule_type"] = "NONSENSE"
    resp = await client.post("/api/v1/alert-rules", json=body)
    assert resp.status_code == 400
