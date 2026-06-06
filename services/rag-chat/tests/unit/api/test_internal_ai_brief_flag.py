"""Unit tests for GET /internal/v1/instruments/{instrument_id}/ai-brief-flag.

PLAN-0089 Wave L-5a (T-WL5A-03).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.application.use_cases.ai_brief_flag import (
    AiBriefFlag,
    GetAiBriefFlagUseCase,
)
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit


_INTERNAL_JWT = _jwt.encode(
    {"sub": "service:test", "tenant_id": "tenant-test", "role": "system"},
    "secret",
    algorithm="HS256",
)
_AUTH_HEADERS = {"X-Internal-JWT": _INTERNAL_JWT}


def _mock_session(latest_at: datetime | None) -> AsyncMock:
    session = AsyncMock()
    session.close = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=(latest_at,) if latest_at is not None else (None,))
    # When no rows exist MAX returns NULL — represented as (None,)
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _build_app(latest_at: datetime | None):
    settings = RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=True,
    )
    app = create_app(settings)

    mock = _mock_session(latest_at)
    # The router's dep grabs ``app.state.read_factory()`` — mock it to return
    # our session directly (no async context manager needed because the dep
    # uses try/finally + ``await session.close()``).
    app.state.read_factory = MagicMock(return_value=mock)
    return app, mock


# ── Use case tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_use_case_no_brief() -> None:
    """No brief → has_ai_brief=False, brief_generated_at=None."""
    session = _mock_session(None)
    out = await GetAiBriefFlagUseCase().execute(session, uuid.uuid4())
    assert isinstance(out, AiBriefFlag)
    assert out.has_ai_brief is False
    assert out.brief_generated_at is None


@pytest.mark.asyncio
async def test_use_case_has_brief() -> None:
    """One brief → has_ai_brief=True with timestamp."""
    when = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    session = _mock_session(when)
    out = await GetAiBriefFlagUseCase().execute(session, uuid.uuid4())
    assert out.has_ai_brief is True
    assert out.brief_generated_at == when


# ── Route tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_200_with_brief() -> None:
    when = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    instrument_id = uuid.uuid4()
    app, _ = _build_app(when)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/ai-brief-flag",
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == str(instrument_id)
    assert body["has_ai_brief"] is True
    assert body["brief_generated_at"] is not None


@pytest.mark.asyncio
async def test_route_200_without_brief() -> None:
    instrument_id = uuid.uuid4()
    app, _ = _build_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/ai-brief-flag",
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_ai_brief"] is False
    assert body["brief_generated_at"] is None


@pytest.mark.asyncio
async def test_route_requires_internal_jwt() -> None:
    instrument_id = uuid.uuid4()
    app, _ = _build_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/ai-brief-flag",
        )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_route_rejects_invalid_uuid() -> None:
    app, _ = _build_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            "/internal/v1/instruments/not-a-uuid/ai-brief-flag",
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 422
