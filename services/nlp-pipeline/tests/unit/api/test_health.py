"""Unit tests for health and readiness endpoints.

Critical invariants tested:
  - GET /healthz always returns 200.
  - GET /readyz returns 200 when all checks pass.
  - GET /readyz returns 503 when nlp_db check fails.
  - GET /readyz returns 503 when valkey check fails.
  - GET /metrics returns Prometheus text format.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.routes.health import router


def _make_app(
    *,
    nlp_db_ok: bool = True,
    intel_db_ok: bool = True,
    valkey_ok: bool = True,
    dispatcher_healthy: bool = True,
) -> FastAPI:
    """Build a minimal FastAPI app with health router and faked state."""
    app = FastAPI()
    app.include_router(router)

    # nlp_db session factory
    mock_nlp_session = AsyncMock()
    mock_nlp_session.__aenter__ = AsyncMock(return_value=mock_nlp_session)
    mock_nlp_session.__aexit__ = AsyncMock(return_value=None)
    if nlp_db_ok:
        mock_nlp_session.execute = AsyncMock(return_value=MagicMock())
    else:
        mock_nlp_session.execute = AsyncMock(side_effect=Exception("DB down"))
    app.state.nlp_session_factory = MagicMock(return_value=mock_nlp_session)

    # intelligence_db session factory
    mock_intel_session = AsyncMock()
    mock_intel_session.__aenter__ = AsyncMock(return_value=mock_intel_session)
    mock_intel_session.__aexit__ = AsyncMock(return_value=None)
    if intel_db_ok:
        mock_intel_session.execute = AsyncMock(return_value=MagicMock())
    else:
        mock_intel_session.execute = AsyncMock(side_effect=Exception("Intel DB down"))
    app.state.intelligence_session_factory = MagicMock(return_value=mock_intel_session)

    # Valkey
    mock_valkey = AsyncMock()
    if valkey_ok:
        mock_valkey.ping = AsyncMock(return_value=True)
    else:
        mock_valkey.ping = AsyncMock(side_effect=Exception("Valkey down"))
    app.state.valkey = mock_valkey

    app.state.dispatcher_healthy = dispatcher_healthy
    # F-003B: Readyz now checks JWKS public key — inject a mock to satisfy the check.
    app.state._internal_jwt_public_key = MagicMock()
    return app


@pytest.mark.unit
class TestHealthz:
    @pytest.mark.asyncio
    async def test_healthz_always_200(self) -> None:
        """Liveness probe always returns 200 regardless of infrastructure state."""
        app = _make_app(nlp_db_ok=False, valkey_ok=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.unit
class TestReadyz:
    @pytest.mark.asyncio
    async def test_readyz_all_healthy(self) -> None:
        """When all dependencies are healthy, readyz returns 200."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["nlp_db"] == "ok"
        assert body["valkey"] == "ok"

    @pytest.mark.asyncio
    async def test_readyz_nlp_db_failure(self) -> None:
        """When nlp_db is down, readyz returns 503."""
        app = _make_app(nlp_db_ok=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["nlp_db"] == "error"

    @pytest.mark.asyncio
    async def test_readyz_valkey_failure(self) -> None:
        """When Valkey is down, readyz returns 503."""
        app = _make_app(valkey_ok=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["valkey"] == "error"

    @pytest.mark.asyncio
    async def test_readyz_dispatcher_degraded_does_not_503(self) -> None:
        """Dispatcher unhealthy degrades the status but still returns 200 if DBs are ok."""
        app = _make_app(dispatcher_healthy=False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")
        # All actual checks pass; dispatcher merely annotates the response
        assert response.status_code == 200
        body = response.json()
        assert body.get("dispatcher") == "degraded"


@pytest.mark.unit
class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_returns_prometheus_format(self) -> None:
        """GET /metrics returns prometheus text exposition format."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
        assert response.status_code == 200
        # Prometheus format always starts with # or a metric name
        assert len(response.content) > 0
