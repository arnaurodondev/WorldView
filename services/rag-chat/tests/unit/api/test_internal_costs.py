"""Unit tests for GET /internal/v1/llm-costs on rag-chat (PLAN-0033 T-E-2-01)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rag_chat.api.routes.internal_costs import LlmCostsResponse, get_rag_read_session, router

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_system_jwt() -> str:
    payload = {
        "iss": "worldview-gateway",
        "sub": "unit-test",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


_SYSTEM_JWT = _make_system_jwt()
_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _SYSTEM_JWT}


def _mock_session(rows: list[dict] | None = None) -> AsyncMock:
    """Build a mock AsyncSession whose execute() returns fake cost rows."""
    session = AsyncMock()
    fake_rows = []
    for row_data in rows or []:
        row = MagicMock()
        for k, v in row_data.items():
            setattr(row, k, v)
        fake_rows.append(row)

    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=fake_rows)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _build_app(rows: list[dict] | None = None) -> FastAPI:
    """Build a minimal FastAPI app with the internal_costs router and mocked session."""
    app = FastAPI()
    app.include_router(router)

    mock = _mock_session(rows)

    async def _mock_read_session():
        yield mock

    app.dependency_overrides[get_rag_read_session] = _mock_read_session
    return app


def _build_auth_app(rows: list[dict] | None = None) -> FastAPI:
    """Build app with InternalJWTMiddleware (skip_verification=True) for 401 tests."""
    from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

    app = FastAPI()
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://test-gateway/internal/jwks",
        skip_verification=True,
    )
    app.include_router(router)

    mock = _mock_session(rows)

    async def _mock_read_session():
        yield mock

    app.dependency_overrides[get_rag_read_session] = _mock_read_session
    return app


# ── Test cases ────────────────────────────────────────────────────────────────


async def test_get_llm_costs_200_provider_breakdown() -> None:
    """Returns 200 with correct structure for breakdown=provider."""
    rows = [
        {
            "dimension": "deepinfra",
            "calls": 120,
            "tokens_in": 480000,
            "tokens_out": 92000,
            "estimated_cost_usd": 0.612,
            "success_rate": 0.97,
        },
    ]
    app = _build_app(rows)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as client:
        resp = await client.get("/internal/v1/llm-costs", params={"period": "2026-04"})

    assert resp.status_code == 200
    body = LlmCostsResponse.model_validate(resp.json())
    assert body.service == "rag-chat"
    assert body.period == "2026-04"
    assert body.total_calls == 120
    assert len(body.breakdown) == 1
    assert body.breakdown[0].dimension == "deepinfra"


async def test_get_llm_costs_default_period_is_current_month() -> None:
    """Omitting period defaults to the current UTC month."""
    from datetime import UTC, datetime

    app = _build_app([])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as client:
        resp = await client.get("/internal/v1/llm-costs")

    assert resp.status_code == 200
    now = datetime.now(tz=UTC)
    assert resp.json()["period"] == f"{now.year:04d}-{now.month:02d}"


async def test_get_llm_costs_invalid_period_400() -> None:
    """period=invalid → HTTP 400."""
    app = _build_app([])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as client:
        resp = await client.get("/internal/v1/llm-costs", params={"period": "2026/04"})

    assert resp.status_code == 400
    assert "YYYY-MM" in resp.json()["detail"]


async def test_get_llm_costs_requires_jwt() -> None:
    """No X-Internal-JWT header → HTTP 401 from InternalJWTMiddleware."""
    app = _build_auth_app([])

    transport = ASGITransport(app=app)
    # Deliberately exclude _INTERNAL_HEADERS to trigger 401
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/v1/llm-costs")

    assert resp.status_code == 401
