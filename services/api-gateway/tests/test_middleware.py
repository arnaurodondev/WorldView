"""Tests for rate limiting middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from api_gateway.middleware import RateLimitMiddleware
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_app(valkey_mock, max_requests: int = 3) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey_mock,
        max_requests=max_requests,
        window_seconds=60,
    )

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_rate_limit_allows_under_threshold() -> None:
    valkey = AsyncMock()
    valkey.incr = AsyncMock(return_value=1)
    valkey.expire = AsyncMock()

    app = _make_app(valkey, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_threshold() -> None:
    valkey = AsyncMock()
    valkey.incr = AsyncMock(return_value=6)  # over the limit

    app = _make_app(valkey, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_failopen_on_valkey_error() -> None:
    valkey = AsyncMock()
    valkey.incr = AsyncMock(side_effect=ConnectionError("valkey down"))

    app = _make_app(valkey, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 200  # fail-open
