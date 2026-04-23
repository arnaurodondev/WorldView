"""Unit tests for GET /internal/v1/llm-costs (PLAN-0033 T-C-3-01)."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.routes.internal_costs import LlmCostsResponse, get_nlp_read_session, router
from nlp_pipeline.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_system_jwt() -> str:
    """Produce a structurally valid JWT (not RS256-verified) for skip_verification tests."""
    payload = {
        "iss": "worldview-gateway",
        "sub": "unit-test-system",
        "tenant_id": "tenant-001",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    # HS256 is intentionally used here because skip_verification=True in tests.
    # A real RS256 key would require a running S9; unit tests bypass verification.
    return jwt.encode(payload, "unit-test-secret", algorithm="HS256")


_SYSTEM_JWT = _make_system_jwt()
_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _SYSTEM_JWT}


def _mock_query_result(rows: list[dict] | None = None) -> AsyncMock:
    """Build a mock SQLAlchemy session whose execute() returns fake cost rows."""
    mock_session = AsyncMock()
    # Each row in the result needs attribute access: row.dimension, row.calls, etc.
    fake_rows = []
    for row_data in rows or []:
        row = MagicMock()
        for k, v in row_data.items():
            setattr(row, k, v)
        fake_rows.append(row)

    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=fake_rows)
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def _build_minimal_app(mock_session: AsyncMock) -> FastAPI:
    """Build a minimal FastAPI app with the internal_costs router and a mocked session."""
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncGenerator:
        yield mock_session

    app.dependency_overrides[get_nlp_read_session] = _override_session
    return app


def _build_auth_app() -> FastAPI:
    """Build a minimal app WITH InternalJWTMiddleware for auth tests."""
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncGenerator:
        yield AsyncMock()

    app.dependency_overrides[get_nlp_read_session] = _override_session

    # InternalJWTMiddleware with skip_verification=True — accepts any JWT or returns 401
    # when X-Internal-JWT header is absent (the 401 path we're testing).
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://unused-in-tests/",
        skip_verification=True,
    )
    return app


# ── Test cases ────────────────────────────────────────────────────────────────


async def test_get_llm_costs_200_provider_breakdown() -> None:
    """GET /internal/v1/llm-costs returns 200 with correct structure for breakdown=provider."""
    rows = [
        {
            "dimension": "ollama",
            "calls": 100,
            "tokens_in": 5000,
            "tokens_out": 1000,
            "estimated_cost_usd": 0.0,
            "success_rate": 1.0,
        },
        {
            "dimension": "deepinfra",
            "calls": 50,
            "tokens_in": 2000,
            "tokens_out": 500,
            "estimated_cost_usd": 0.01,
            "success_rate": 0.98,
        },
    ]
    mock_session = _mock_query_result(rows)
    app = _build_minimal_app(mock_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/llm-costs",
            params={"period": "2026-04", "breakdown": "provider"},
        )

    assert resp.status_code == 200
    body = LlmCostsResponse.model_validate(resp.json())
    assert body.service == "nlp-pipeline"
    assert body.period == "2026-04"
    assert body.total_calls == 150
    assert body.total_tokens_in == 7000
    assert body.total_tokens_out == 1500
    assert abs(body.total_estimated_cost_usd - 0.01) < 1e-9
    assert len(body.breakdown) == 2
    assert body.breakdown[0].dimension == "ollama"


async def test_get_llm_costs_default_period_is_current_month() -> None:
    """Omitting period defaults to the current UTC month (YYYY-MM)."""
    from datetime import UTC, datetime

    mock_session = _mock_query_result([])
    app = _build_minimal_app(mock_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/v1/llm-costs")

    assert resp.status_code == 200
    body = resp.json()
    now = datetime.now(tz=UTC)
    expected_period = f"{now.year:04d}-{now.month:02d}"
    assert body["period"] == expected_period


async def test_get_llm_costs_invalid_period_400() -> None:
    """period=bad-format → HTTP 400."""
    mock_session = _mock_query_result([])
    app = _build_minimal_app(mock_session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/v1/llm-costs", params={"period": "not-a-month"})

    assert resp.status_code == 400
    assert "YYYY-MM" in resp.json().get("detail", "")


async def test_get_llm_costs_requires_jwt() -> None:
    """No X-Internal-JWT header → HTTP 401 from InternalJWTMiddleware."""
    app = _build_auth_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No X-Internal-JWT header → middleware returns 401 before reaching the route
        resp = await client.get("/internal/v1/llm-costs")

    assert resp.status_code == 401
