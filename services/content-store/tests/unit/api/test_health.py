"""Unit tests for health, readiness, and metrics endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Liveness ─────────────────────────────────────────────────────────────────


async def test_healthz_returns_200(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Readiness ────────────────────────────────────────────────────────────────


async def test_readyz_ok_when_all_checks_pass(app, client):
    """Readyz returns 200 when DB and Valkey are reachable."""
    # The mock session factory from conftest makes DB appear healthy
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    async def _factory():
        return mock_session

    # Make the factory a proper async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    app.state.session_factory = lambda: cm

    app.state.valkey = None  # skip valkey check
    app.state.consumer_alive = True

    resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["consumer"] == "ok"


async def test_readyz_503_when_consumer_dead(app, client):
    """Readyz returns 503 when consumer is not alive."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    app.state.session_factory = lambda: cm

    app.state.valkey = None
    app.state.consumer_alive = False

    resp = await client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["consumer"] == "error"


# ── Metrics ──────────────────────────────────────────────────────────────────


async def test_metrics_endpoint_returns_prometheus(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"] or "text/plain" in resp.headers.get("content-type", "")
    body = resp.text
    # Should contain at least one of our custom metrics
    assert "s5_articles_received_total" in body or "s5_canonical_written_total" in body
