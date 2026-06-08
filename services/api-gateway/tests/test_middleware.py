"""Tests for rate limiting middleware and auth skip paths."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from api_gateway.middleware import _AUTH_SKIP_PATHS, RateLimitMiddleware
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit


def _make_app(valkey_mock, max_requests: int = 3, extra_routes: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey_mock,
        max_requests=max_requests,
        window_seconds=60,
        # F-TEST-001..008: PLAN-0094 W1 added three keyword-only sibling limits
        # to RateLimitMiddleware.  Pass test defaults that match the production
        # config values in api_gateway.config.Settings (20/20/120) so the test
        # buckets behave like prod for skip-path / threshold cases.
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    if extra_routes:

        @app.get("/healthz")
        async def healthz():
            return {"status": "ok"}

        @app.get("/readyz")
        async def readyz():
            return {"status": "ok"}

        @app.get("/metrics")
        async def metrics():
            return {"metrics": "ok"}

        @app.get("/internal/jwks")
        async def jwks():
            return {"keys": []}

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
    # Unauthenticated limit is hardcoded to 20; return value must exceed that
    valkey.incr = AsyncMock(return_value=21)

    app = _make_app(valkey, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_failclosed_on_valkey_error() -> None:
    """D-001: When Valkey operation fails, return 503 (fail-closed)."""
    valkey = AsyncMock()
    valkey.incr = AsyncMock(side_effect=ConnectionError("valkey down"))

    app = _make_app(valkey, max_requests=5)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 503  # D-001: fail-closed


# ── F-05: Rate limiter skips health/metrics/internal paths ────────────────────


@pytest.mark.asyncio
async def test_rate_limit_skips_healthz() -> None:
    """F-05: /healthz is never rate-limited, even when Valkey is None."""
    app = _make_app(valkey_mock=None, extra_routes=True)
    # Set app.state.valkey to None so the rate limiter would normally return 503
    app.state.valkey = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_skips_readyz() -> None:
    """F-05: /readyz is never rate-limited, even when Valkey is None."""
    app = _make_app(valkey_mock=None, extra_routes=True)
    app.state.valkey = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/readyz")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_skips_metrics() -> None:
    """F-05: /metrics is never rate-limited, even when Valkey is None."""
    app = _make_app(valkey_mock=None, extra_routes=True)
    app.state.valkey = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_skips_internal_jwks() -> None:
    """F-05: /internal/jwks is never rate-limited, even when Valkey is None."""
    app = _make_app(valkey_mock=None, extra_routes=True)
    app.state.valkey = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/jwks")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_still_applies_to_api_paths() -> None:
    """F-05: API paths are still rate-limited when Valkey is None → 503."""
    app = _make_app(valkey_mock=None, extra_routes=True)
    app.state.valkey = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")
        assert resp.status_code == 503  # fail-closed for API paths


# ── F-01: _AUTH_SKIP_PATHS correctness ────────────────────────────────────────


def test_auth_skip_paths_has_healthz_not_health() -> None:
    """F-01: /healthz is in _AUTH_SKIP_PATHS, not the dead /health."""
    assert "/healthz" in _AUTH_SKIP_PATHS
    assert "/health" not in _AUTH_SKIP_PATHS


def test_auth_skip_paths_has_readyz_not_ready() -> None:
    """F-01: /readyz is in _AUTH_SKIP_PATHS, not the dead /ready."""
    assert "/readyz" in _AUTH_SKIP_PATHS
    assert "/ready" not in _AUTH_SKIP_PATHS


def test_auth_skip_paths_contains_expected_entries() -> None:
    """Verify _AUTH_SKIP_PATHS contains all expected paths."""
    expected = {
        "/v1/auth/login",
        "/v1/auth/callback",
        "/v1/auth/refresh",
        "/v1/auth/logout",
        "/healthz",
        "/v1/healthz",  # Dashboard Regression #5 followup: versioned alias
        "/readyz",
        "/v1/health",  # PLAN-0088 P2-D: external uptime monitor alias
        "/metrics",
        "/internal/jwks",
    }
    assert _AUTH_SKIP_PATHS == expected
