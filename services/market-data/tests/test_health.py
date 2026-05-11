"""Health endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_readyz(e2e_live_client) -> None:
    """Readyz needs real DB — e2e only, not unit. Requires live service on localhost:8003."""
    response = await e2e_live_client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
