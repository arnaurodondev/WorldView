"""Observability wiring tests for portfolio (PLAN-0003 T-B-2-01)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.app import RequestIdMiddleware, create_app
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unit


@pytest.fixture
def obs_app():
    return create_app()


@pytest.fixture
async def obs_client(obs_app):
    transport = ASGITransport(app=obs_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_request_id_middleware_registered(obs_app) -> None:
    """RequestIdMiddleware should be registered on the app."""
    middleware_classes = [m.cls for m in obs_app.user_middleware if hasattr(m, "cls")]
    assert RequestIdMiddleware in middleware_classes


def test_request_id_middleware_is_base_http_middleware() -> None:
    """RequestIdMiddleware should extend BaseHTTPMiddleware."""
    assert issubclass(RequestIdMiddleware, BaseHTTPMiddleware)


async def test_request_id_generated_when_missing(obs_client) -> None:
    """Missing X-Request-ID should be generated."""
    response = await obs_client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


async def test_request_id_preserved_when_present(obs_client) -> None:
    """Existing X-Request-ID should be echoed back."""
    custom_id = "test-portfolio-req-id"
    response = await obs_client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.headers["x-request-id"] == custom_id
