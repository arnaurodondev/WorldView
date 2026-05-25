"""Health endpoint tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio()
async def test_readyz(client) -> None:
    # Wave D-4: readyz now performs a real intelligence_db connectivity check (SELECT 1).
    # Without a live database configured in the unit test client, the DB check fails
    # and the endpoint correctly returns 503 "degraded". The 200 "ok" path is covered
    # by integration tests in tests/integration/ which use a real Postgres instance.
    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    # The test client doesn't wire a session_factory, so intelligence_db reports "not_configured"
    assert body["intelligence_db"] in ("error", "not_configured")
