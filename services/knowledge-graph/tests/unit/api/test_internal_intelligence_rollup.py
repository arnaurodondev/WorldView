"""Unit tests for GET /internal/v1/instruments/{instrument_id}/intelligence-rollup-7d.

PLAN-0089 Wave L-5a (T-WL5A-01).
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.api.dependencies import get_readonly_session
from knowledge_graph.app import create_app
from knowledge_graph.application.use_cases.intelligence_rollup import (
    GetIntelligenceRollup7dUseCase,
    IntelligenceRollup7d,
)
from knowledge_graph.config import Settings

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


_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _make_system_jwt()}


def _mock_session(count: int | None) -> AsyncMock:
    """Return an AsyncSession mock whose execute() returns a single-row count."""
    session = AsyncMock()
    mock_result = MagicMock()
    if count is None:
        mock_result.fetchone = MagicMock(return_value=None)
    else:
        mock_result.fetchone = MagicMock(return_value=(count,))
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _build_app(count: int | None):
    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]
    mock = _mock_session(count)

    async def _ro():
        yield mock

    app.dependency_overrides[get_readonly_session] = _ro
    return app, mock


# ── Use case tests ────────────────────────────────────────────────────────────


async def test_use_case_returns_zero_when_no_rows() -> None:
    """No matching row → recent_contradiction_count = 0 (R11 safe default)."""
    session = _mock_session(None)
    out = await GetIntelligenceRollup7dUseCase().execute(session, uuid.uuid4())
    assert isinstance(out, IntelligenceRollup7d)
    assert out.recent_contradiction_count == 0


async def test_use_case_returns_count() -> None:
    """SUM(contradictions) is returned verbatim."""
    session = _mock_session(7)
    out = await GetIntelligenceRollup7dUseCase().execute(session, uuid.uuid4())
    assert out.recent_contradiction_count == 7


async def test_use_case_zero_count_explicit() -> None:
    """COUNT() returns 0 (not NULL) when no rows match — confirm we handle it."""
    session = _mock_session(0)
    out = await GetIntelligenceRollup7dUseCase().execute(session, uuid.uuid4())
    assert out.recent_contradiction_count == 0


# ── Route tests ───────────────────────────────────────────────────────────────


async def test_route_200_with_count() -> None:
    """Happy path: 200 with the entity_id echoed and the count returned."""
    instrument_id = uuid.uuid4()
    app, _ = _build_app(3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/intelligence-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == str(instrument_id)
    assert body["recent_contradiction_count"] == 3


async def test_route_200_when_no_entity_or_no_contradictions() -> None:
    """Missing/silent entity → 200 with count=0 (NOT 404, per L-5b contract)."""
    instrument_id = uuid.uuid4()
    app, _ = _build_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/intelligence-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recent_contradiction_count"] == 0


async def test_route_requires_internal_jwt() -> None:
    """Missing X-Internal-JWT header → 401 from InternalJWTMiddleware."""
    instrument_id = uuid.uuid4()
    app, _ = _build_app(0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/intelligence-rollup-7d",
        )
    assert resp.status_code in (401, 403)


async def test_route_rejects_invalid_uuid() -> None:
    """422 path-validation error for non-UUID instrument_id."""
    app, _ = _build_app(0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            "/internal/v1/instruments/not-a-uuid/intelligence-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 422
