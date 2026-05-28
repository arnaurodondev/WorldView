"""Unit tests for GET /internal/v1/instruments/{instrument_id}/active-alert-flag.

PLAN-0089 Wave L-5a (T-WL5A-02).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt
import pytest
from alert.api.dependencies import get_read_db_session
from alert.app import create_app
from alert.application.use_cases.active_alert_flag import (
    ActiveAlertFlag,
    GetActiveAlertFlagUseCase,
)
from alert.config import Settings
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from fastapi import FastAPI


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_system_jwt() -> str:
    return jwt.encode(
        {
            "sub": "service:test",
            "tenant_id": "tenant-test",
            "role": "system",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "secret",
        algorithm="HS256",
    )


_INTERNAL_HEADERS = {"X-Internal-JWT": _make_system_jwt()}


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


def _build_app(count: int | None) -> tuple[FastAPI, AsyncMock]:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        admin_token="test-admin",
        service_name="alert-unit-test",
        log_json=False,
        s8_internal_jwt="test-s8-token",
        s1_internal_token="test-s1-token",
        internal_jwt_skip_verification=True,
    )
    app = create_app(settings)
    # Minimal infrastructure wiring so the app boots — write factory unused here.
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=False)
    app.state.session_factory = MagicMock(return_value=write_session)

    mock = _mock_session(count)

    async def _ro():
        yield mock

    app.dependency_overrides[get_read_db_session] = _ro
    return app, mock


# ── Use case tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_use_case_false_when_no_alerts() -> None:
    session = _mock_session(0)
    out = await GetActiveAlertFlagUseCase().execute(session, uuid.uuid4())
    assert isinstance(out, ActiveAlertFlag)
    assert out.has_active_alert is False
    assert out.active_alert_count == 0


@pytest.mark.asyncio
async def test_use_case_true_when_one_or_more() -> None:
    session = _mock_session(4)
    out = await GetActiveAlertFlagUseCase().execute(session, uuid.uuid4())
    assert out.has_active_alert is True
    assert out.active_alert_count == 4


@pytest.mark.asyncio
async def test_use_case_handles_null_row() -> None:
    """COUNT() will not return NULL but defensive code handles it anyway."""
    session = _mock_session(None)
    out = await GetActiveAlertFlagUseCase().execute(session, uuid.uuid4())
    assert out.has_active_alert is False
    assert out.active_alert_count == 0


# ── Route tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_200_active() -> None:
    instrument_id: UUID = uuid.uuid4()
    app, _ = _build_app(2)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/active-alert-flag",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument_id"] == str(instrument_id)
    assert body["has_active_alert"] is True
    assert body["active_alert_count"] == 2


@pytest.mark.asyncio
async def test_route_200_inactive() -> None:
    instrument_id: UUID = uuid.uuid4()
    app, _ = _build_app(0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/active-alert-flag",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_active_alert"] is False
    assert body["active_alert_count"] == 0


@pytest.mark.asyncio
async def test_route_requires_internal_jwt() -> None:
    instrument_id = uuid.uuid4()
    app, _ = _build_app(0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/instruments/{instrument_id}/active-alert-flag",
        )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_route_rejects_invalid_uuid() -> None:
    app, _ = _build_app(0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            "/internal/v1/instruments/not-a-uuid/active-alert-flag",
            headers=_INTERNAL_HEADERS,
        )
    assert resp.status_code == 422
