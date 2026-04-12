"""Observability wiring tests for market-ingestion (PLAN-0003 T-B-1-01)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.app import RequestIdMiddleware, create_app
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unit


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_create_app_has_request_id_middleware(app) -> None:
    """RequestIdMiddleware should be registered on the app."""
    middleware_classes = [m.cls for m in app.user_middleware if hasattr(m, "cls")]
    assert RequestIdMiddleware in middleware_classes


def test_request_id_middleware_is_base_http_middleware() -> None:
    """RequestIdMiddleware should extend BaseHTTPMiddleware (not inline decorator)."""
    assert issubclass(RequestIdMiddleware, BaseHTTPMiddleware)


async def test_healthz_returns_ok(client) -> None:
    """GET /healthz should return 200 with status ok."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_request_id_generated_when_missing(client) -> None:
    """When no X-Request-ID header is sent, one should be generated in response."""
    response = await client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


async def test_request_id_preserved_when_present(client) -> None:
    """When X-Request-ID is sent, it should be echoed back."""
    custom_id = "test-request-id-12345"
    response = await client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.headers["x-request-id"] == custom_id


async def test_request_id_rejects_invalid_header(client) -> None:
    """Invalid X-Request-ID (special chars, too long) should be replaced with generated ULID."""
    # Newline injection attempt
    response = await client.get("/healthz", headers={"X-Request-ID": "abc\ndef"})
    assert response.headers["x-request-id"] != "abc\ndef"
    assert len(response.headers["x-request-id"]) > 0

    # Excessively long value (>64 chars)
    long_id = "a" * 100
    response = await client.get("/healthz", headers={"X-Request-ID": long_id})
    assert response.headers["x-request-id"] != long_id

    # Special characters
    response = await client.get("/healthz", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert response.headers["x-request-id"] != "<script>alert(1)</script>"


async def test_metrics_endpoint_returns_prometheus() -> None:
    """GET /metrics returns prometheus text format (PRD-0025: /metrics is in _SKIP_PREFIXES)."""
    test_app = create_app()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
