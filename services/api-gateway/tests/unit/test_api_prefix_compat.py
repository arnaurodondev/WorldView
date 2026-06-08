"""Regression test for Dashboard Regression #5 — /api/v1 prefix compatibility.

WHY: The frontend issues requests against `/api/v1/...` (apps/worldview-web/
lib/api/_client.ts sets BASE="/api"). In production, the ingress forwards the
path verbatim and the gateway must resolve both `/v1/...` and `/api/v1/...`
to the same route. A starlette middleware in ``api_gateway.app`` strips the
`/api` prefix at request time so both URL spaces share one router tree.

If this test fails, the production routing fix is broken and dashboard calls
like `GET /api/v1/market/top-movers` will 404 again.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_v1_and_api_v1_resolve_same_route(app) -> None:
    """`/healthz` and `/api/healthz` must return identical responses."""
    client = TestClient(app)

    # /healthz is an unauthenticated route on the health router (routes/health.py:12).
    # Using a top-level /healthz works because the strip middleware drops the /api
    # segment ("/api/healthz" → "/healthz") before routing.
    r1 = client.get("/healthz")
    r2 = client.get("/api/healthz")

    assert r1.status_code == 200, f"baseline /healthz failed: {r1.status_code}"
    assert r2.status_code == r1.status_code, f"/api prefix not stripped — got {r2.status_code} vs {r1.status_code}"
    assert r2.json() == r1.json()


def test_api_v1_health_resolves_same_as_v1_health(app) -> None:
    """`/v1/health` and `/api/v1/health` must return identical responses.

    Covers the exact path skew seen in production (Cloudflare egress logged
    `GET /api/v1/market/top-movers` 404). Uses /v1/health since it requires
    no service-client mocking.
    """
    client = TestClient(app)

    r1 = client.get("/v1/health")
    r2 = client.get("/api/v1/health")

    assert r1.status_code == 200
    assert r2.status_code == r1.status_code
    assert r2.json() == r1.json()
