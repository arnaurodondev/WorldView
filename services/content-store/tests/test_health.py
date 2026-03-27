"""Health endpoint smoke tests.

More comprehensive health/readiness tests are in tests/unit/api/test_health.py.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_healthz(client) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readyz_returns_valid_response(client) -> None:
    """Readyz returns either 200 (ok) or 503 (degraded) — both are valid shapes."""
    response = await client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ok", "degraded")
