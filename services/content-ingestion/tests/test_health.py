"""Health endpoint tests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz(client) -> None:
    response = await client.get("/readyz")
    # Unit test client does not provision DB/Valkey, so readiness is degraded.
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
