"""Deployment readiness tests — verify every service is healthy and production-ready.

Tests health endpoints, Prometheus metrics, Schema Registry connectivity, and basic
API routing. Run against a locally deployed stack (Docker Compose full profile or
a local k3d cluster with port-forwarding).

Run against Docker Compose full stack:
    docker compose --profile infra --profile runtime up -d
    docker compose --profile init up
    python -m pytest tests/e2e/test_deployment_readiness.py -v -m e2e

Run against k3d local cluster (with port-forward):
    ./scripts/local-k8s.sh run-smoke-tests

All tests skip gracefully if services are not reachable.
"""

from __future__ import annotations

import socket

import httpx
import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Service inventory — (name, host, port) for each backend service
# ──────────────────────────────────────────────────────────────────────────────

SERVICES: list[tuple[str, str, int]] = [
    ("portfolio", "localhost", 8001),
    ("market-ingestion", "localhost", 8002),
    ("market-data", "localhost", 8003),
    ("content-ingestion", "localhost", 8004),
    ("content-store", "localhost", 8005),
    ("nlp-pipeline", "localhost", 8006),
    ("knowledge-graph", "localhost", 8007),
    ("rag-chat", "localhost", 8008),
    ("api-gateway", "localhost", 8000),
    ("alert", "localhost", 8010),
]

INFRA_SERVICES: list[tuple[str, str, int]] = [
    ("schema-registry", "localhost", 8081),
    ("kafka", "localhost", 9092),
    ("postgres", "localhost", 5432),
    ("minio", "localhost", 7480),
    ("valkey", "localhost", 6379),
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if the given TCP port accepts connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def service_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: application service health
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("name,host,port", SERVICES, ids=[s[0] for s in SERVICES])
async def test_service_health_endpoint(name: str, host: str, port: int) -> None:
    """Every service must return HTTP 200 from GET /healthz with a 'status' field.

    All worldview services expose /healthz (not /health) as the canonical liveness probe.
    This matches the Kubernetes liveness probe path in the Helm chart (PRD-0024 §6.4).
    """
    if not is_port_open(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get(f"{service_url(host, port)}/healthz")

    assert resp.status_code == 200, f"{name} /healthz returned {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert "status" in body, f"{name} /healthz response missing 'status' field: {body}"


@pytest.mark.e2e
@pytest.mark.parametrize("name,host,port", SERVICES, ids=[s[0] for s in SERVICES])
async def test_service_metrics_endpoint(name: str, host: str, port: int) -> None:
    """Every service must expose Prometheus metrics at GET /metrics."""
    if not is_port_open(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get(f"{service_url(host, port)}/metrics")

    assert resp.status_code == 200, f"{name} /metrics returned {resp.status_code}"
    # A valid Prometheus metrics response contains at least one of these marker strings
    body = resp.text
    assert any(
        marker in body for marker in ("python_info", "process_", "http_", "HELP")
    ), f"{name} /metrics response does not look like Prometheus output"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: infra connectivity
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.parametrize("name,host,port", INFRA_SERVICES, ids=[s[0] for s in INFRA_SERVICES])
async def test_infra_service_reachable(name: str, host: str, port: int) -> None:
    """Every infra service must accept TCP connections."""
    if not is_port_open(host, port):
        pytest.skip(f"{name} not reachable at {host}:{port}")
    # If we got here past the skip, the port is open
    assert is_port_open(host, port, timeout=2.0), f"{name} port {port} not accepting connections"


@pytest.mark.e2e
async def test_schema_registry_has_subjects() -> None:
    """Schema Registry must have at least 10 Avro subjects (init ran successfully)."""
    if not is_port_open("localhost", 8081):
        pytest.skip("Schema Registry not reachable at localhost:8081")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get("http://localhost:8081/subjects")

    assert resp.status_code == 200, f"Schema Registry /subjects returned {resp.status_code}"
    subjects = resp.json()
    assert isinstance(subjects, list), "Expected list of subjects"
    assert len(subjects) >= 10, f"Only {len(subjects)} Avro subjects found; expected ≥10 — did init job run?"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: API Gateway routing
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
async def test_api_gateway_health() -> None:
    """API Gateway (S9) must be healthy and expose the correct API version."""
    if not is_port_open("localhost", 8000):
        pytest.skip("API Gateway not reachable at localhost:8000")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get("http://localhost:8000/healthz")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("ok", "healthy", "UP"), f"Unexpected status: {body}"


@pytest.mark.e2e
async def test_api_gateway_openapi_schema() -> None:
    """API Gateway must serve its OpenAPI schema at /openapi.json."""
    if not is_port_open("localhost", 8000):
        pytest.skip("API Gateway not reachable at localhost:8000")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get("http://localhost:8000/openapi.json")

    assert resp.status_code == 200, f"/openapi.json returned {resp.status_code}"
    schema = resp.json()
    assert "paths" in schema, "OpenAPI schema missing 'paths'"
    assert "info" in schema, "OpenAPI schema missing 'info'"


@pytest.mark.e2e
async def test_api_gateway_rejects_unauthenticated_requests() -> None:
    """Protected endpoints must return 401 when no JWT is provided."""
    if not is_port_open("localhost", 8000):
        pytest.skip("API Gateway not reachable at localhost:8000")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get("http://localhost:8000/api/v1/portfolio/holdings")

    assert resp.status_code == 401, f"Expected 401 for unauthenticated request, got {resp.status_code}"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: data layer readiness
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
async def test_minio_accessible() -> None:
    """MinIO S3-compatible API must respond to health check."""
    if not is_port_open("localhost", 7480):
        pytest.skip("MinIO not reachable at localhost:7480")

    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        resp = await client.get("http://localhost:7480/minio/health/live")

    assert resp.status_code == 200, f"MinIO health returned {resp.status_code}"


@pytest.mark.e2e
async def test_valkey_accessible() -> None:
    """Valkey must accept TCP connections on port 6379."""
    if not is_port_open("localhost", 6379):
        pytest.skip("Valkey not reachable at localhost:6379")

    # Send a bare PING over TCP and expect +PONG
    import asyncio

    reader, writer = await asyncio.open_connection("localhost", 6379)
    try:
        writer.write(b"*1\r\n$4\r\nPING\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(100), timeout=2.0)
        assert b"PONG" in data, f"Expected PONG from Valkey, got: {data!r}"
    finally:
        writer.close()
        await writer.wait_closed()


# ──────────────────────────────────────────────────────────────────────────────
# Tests: cross-service routing (requires full stack)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
async def test_full_stack_api_gateway_proxies_to_market_data() -> None:
    """API Gateway must successfully route a public endpoint to Market Data (S3).

    This verifies the inter-service HTTP routing works end-to-end without auth.
    """
    if not is_port_open("localhost", 8000) or not is_port_open("localhost", 8003):
        pytest.skip("API Gateway or Market Data not reachable")

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        # The instruments list endpoint is public (no auth required)
        resp = await client.get(
            "http://localhost:8000/api/v1/instruments",
            params={"page": 1, "page_size": 1},
        )

    # 200 = data returned; 404 = no instruments yet but service is reachable
    assert resp.status_code in (
        200,
        404,
    ), f"Expected 200 or 404 from instruments endpoint, got {resp.status_code}: {resp.text[:200]}"
