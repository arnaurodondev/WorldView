"""Health and provider-status endpoint tests (Wave D-3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


async def test_healthz_always_200(client) -> None:
    """GET /healthz returns 200 regardless of infrastructure availability."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_503_on_db_failure(client) -> None:
    """GET /readyz returns 503 when rag_db (and other deps) are unavailable.

    In unit tests no real DB, Ollama, or Valkey is running, so all three
    readiness checks fail and the endpoint must return 503.
    """
    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["rag_db"] == "error"


async def test_providers_status_200(client) -> None:
    """GET /api/v1/providers/status returns 200 with a providers list."""
    response = await client.get("/api/v1/providers/status")
    assert response.status_code == 200
    body = response.json()
    assert "providers" in body
    names = {p["name"] for p in body["providers"]}
    assert names == {"deepinfra", "openrouter", "ollama"}
    for provider in body["providers"]:
        assert "available" in provider
        assert "model" in provider
