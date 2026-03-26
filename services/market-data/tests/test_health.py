"""Health endpoint tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_readyz(client) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
