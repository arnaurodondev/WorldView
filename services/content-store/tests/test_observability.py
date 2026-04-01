"""Observability wiring tests for content-store (PLAN-0003 T-B-1-02)."""

from __future__ import annotations

import pytest
from content_store.app import RequestIdMiddleware, create_app
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
def obs_app():
    """App created via the real factory (ASGI transport, no lifespan trigger)."""
    return create_app()


@pytest.fixture
async def obs_client(obs_app):
    transport = ASGITransport(app=obs_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_create_app_has_request_id_middleware(obs_app) -> None:
    """RequestIdMiddleware should be registered on the app."""
    middleware_classes = [m.cls for m in obs_app.user_middleware if hasattr(m, "cls")]
    assert RequestIdMiddleware in middleware_classes


def test_request_id_middleware_is_base_http_middleware() -> None:
    """RequestIdMiddleware should extend BaseHTTPMiddleware."""
    assert issubclass(RequestIdMiddleware, BaseHTTPMiddleware)


async def test_request_id_generated_when_missing(obs_client) -> None:
    """When no X-Request-ID header is sent, one should be generated in response."""
    response = await obs_client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


async def test_request_id_preserved_when_present(obs_client) -> None:
    """When X-Request-ID is sent, it should be echoed back."""
    custom_id = "test-request-id-67890"
    response = await obs_client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.headers["x-request-id"] == custom_id
