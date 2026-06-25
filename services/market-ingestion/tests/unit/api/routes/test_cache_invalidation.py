"""Integration-style unit tests for the cache invalidation admin endpoint
(PLAN-0108 Wave E).

Uses the real FastAPI app via ASGITransport with ``internal_jwt_skip_verification=True``
so the InternalJWTMiddleware lets the request through to the route without
requiring a real JWKS keypair. Authentication is tested separately in
``test_internal_jwt_middleware.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from market_ingestion.app import create_app
from market_ingestion.application.metrics.cache import provider_cache_invalidated_total
from market_ingestion.config import Settings

pytestmark = pytest.mark.unit


def _build_app_with_cache(*, delete_pattern_return: int = 2):
    """Build the app and wire a stub MarketDataCache onto ``app.state``.

    The dependency provider reads ``app.state.market_data_cache`` -- injecting
    a mock here gives us deterministic ``keys_deleted`` results without
    standing up a real Valkey instance.
    """
    from market_ingestion.infrastructure.cache.market_data_cache import MarketDataCache

    settings = Settings(internal_jwt_skip_verification=True)  # type: ignore[call-arg]
    app = create_app(settings)

    # Build a real MarketDataCache backed by an AsyncMock ValkeyClient so the
    # invalidate() method exercises its actual code path (key-prefix build +
    # delete_pattern delegation).
    valkey = AsyncMock()
    valkey.delete_pattern = AsyncMock(return_value=delete_pattern_return)
    app.state.market_data_cache = MarketDataCache(valkey)
    return app, valkey


@pytest.mark.asyncio
async def test_invalidate_cache_success_returns_keys_deleted() -> None:
    """DELETE with valid dataset_type + symbol returns 200 with key count, and
    the audit metric increments by that count.
    """
    label = "ohlcv_eod"
    before = provider_cache_invalidated_total.labels(dataset_type=label)._value.get()  # type: ignore[attr-defined]

    app, valkey = _build_app_with_cache(delete_pattern_return=4)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/internal/v1/cache/ohlcv_eod/AAPL",
            headers={"X-Internal-JWT": "ignored.in.skip.mode"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"dataset_type": "ohlcv_eod", "symbol": "AAPL", "keys_deleted": 4}

    # Confirm the cache actually fanned out to delete_pattern with the canonical
    # key shape -- this protects against accidental key-format drift.
    valkey.delete_pattern.assert_awaited_once_with("market_data:ohlcv_eod:aapl:*")

    after = provider_cache_invalidated_total.labels(dataset_type=label)._value.get()  # type: ignore[attr-defined]
    assert after - before == 4


@pytest.mark.asyncio
async def test_invalidate_cache_unknown_dataset_type_returns_400() -> None:
    """Path param that is not a DatasetType member returns 400."""
    app, _ = _build_app_with_cache()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/internal/v1/cache/not_a_real_dataset/AAPL",
            headers={"X-Internal-JWT": "ignored.in.skip.mode"},
        )

    assert resp.status_code == 400
    assert "unknown dataset_type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalidate_cache_rejects_missing_jwt() -> None:
    """Without X-Internal-JWT, the InternalJWTMiddleware returns 401 even when
    skip_verification is False (the default production config).
    """
    # Use the production-default settings (no skip_verification override) so
    # the middleware enforces the header check on /internal/* routes.
    settings = Settings()  # type: ignore[call-arg]
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/internal/v1/cache/ohlcv_eod/AAPL")
    assert resp.status_code == 401
