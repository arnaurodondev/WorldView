"""Unit tests for GET /internal/v1/instruments/{instrument_id}/news-rollup-7d.

PLAN-0089 Wave L-5a (T-WL5A-04).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_read_nlp_session
from nlp_pipeline.api.routes.internal_news_rollup import router
from nlp_pipeline.application.use_cases.news_rollup_7d import (
    GetNewsRollup7dUseCase,
    NewsRollup7d,
)
from nlp_pipeline.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

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
    return jwt.encode(payload, "unit-test-secret", algorithm="HS256")


_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _make_system_jwt()}


def _mock_session(row: tuple | None) -> AsyncMock:
    """Return a session mock whose execute() returns a single 3-column row.

    Pass ``None`` to simulate fetchone returning None (defensive path).
    """
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _build_app(row: tuple | None) -> FastAPI:
    """Build a minimal app that includes the news-rollup router only."""
    app = FastAPI()
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url="http://localhost:9999/internal/jwks",
        skip_verification=True,
    )
    app.include_router(router)

    session = _mock_session(row)

    async def _override() -> AsyncGenerator[Any, None]:
        yield session

    app.dependency_overrides[get_read_nlp_session] = _override
    return app


# ── Use case tests ────────────────────────────────────────────────────────────


async def test_use_case_empty_window() -> None:
    """No articles → counts/maxes zero/None."""
    session = _mock_session((0, None, None))
    out = await GetNewsRollup7dUseCase().execute(session, uuid.uuid4())
    assert isinstance(out, NewsRollup7d)
    assert out.news_count_7d == 0
    assert out.llm_relevance_7d_max is None
    assert out.display_relevance_7d_weighted is None


async def test_use_case_populated() -> None:
    """Populated window — verify numeric coercion from Decimal."""
    session = _mock_session((5, Decimal("0.82"), Decimal("0.65")))
    out = await GetNewsRollup7dUseCase().execute(session, uuid.uuid4())
    assert out.news_count_7d == 5
    assert out.llm_relevance_7d_max is not None
    assert abs(out.llm_relevance_7d_max - 0.82) < 1e-9
    assert out.display_relevance_7d_weighted is not None


async def test_use_case_handles_none_row() -> None:
    """Defensive: session returns no row → zero defaults."""
    session = _mock_session(None)
    out = await GetNewsRollup7dUseCase().execute(session, uuid.uuid4())
    assert out.news_count_7d == 0
    assert out.llm_relevance_7d_max is None
    assert out.display_relevance_7d_weighted is None


# ── Route tests ───────────────────────────────────────────────────────────────


async def test_route_200_populated() -> None:
    instrument_id = uuid.uuid4()
    app = _build_app((7, Decimal("0.9"), Decimal("0.7")))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/news-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == str(instrument_id)
    assert body["news_count_7d"] == 7
    assert body["llm_relevance_7d_max"] == pytest.approx(0.9)
    assert body["display_relevance_7d_weighted"] == pytest.approx(0.7)


async def test_route_200_empty_window() -> None:
    instrument_id = uuid.uuid4()
    app = _build_app((0, None, None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/news-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["news_count_7d"] == 0
    assert body["llm_relevance_7d_max"] is None
    assert body["display_relevance_7d_weighted"] is None


async def test_route_requires_internal_jwt() -> None:
    instrument_id = uuid.uuid4()
    app = _build_app((0, None, None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/news-rollup-7d",
        )
    assert resp.status_code in (401, 403)


async def test_route_rejects_invalid_uuid() -> None:
    app = _build_app((0, None, None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            "/internal/v1/instruments/not-a-uuid/news-rollup-7d",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 422


def test_router_is_registered_in_create_app() -> None:
    """Regression: news-rollup router must be wired into the production app.

    The router existed since L-5a but was never imported by ``app.py``,
    causing the L-5b nightly sync worker to 404 on all 664 instruments and
    silently leave news_count_7d / llm_relevance_7d_max /
    display_relevance_7d_weighted columns NULL forever.
    """
    from nlp_pipeline.app import create_app
    from nlp_pipeline.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://x/y",  # - test placeholder
        intelligence_database_url="postgresql+asyncpg://x/y",
    )
    app = create_app(settings=settings)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/internal/v1/instruments/{instrument_id}/news-rollup-7d" in paths
