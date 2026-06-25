"""Unit tests for GET /internal/v1/users/{user_id}/alerts/pending.

PLAN-0094 follow-up: the service-caller variant of /api/v1/alerts/pending.
The rag-chat morning-brief scheduler holds a single service-account JWT
(role="system", service_name="rag-chat-brief-scheduler") whose subject does
NOT map to a real user, so it reads each user's alerts via this path-scoped
route. Regression guard for the morning-brief 403 / s5_client_error.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from alert.api.dependencies import get_pending_alerts_uc
from alert.app import create_app
from alert.config import Settings
from alert.domain.entities import Alert, PendingAlert
from alert.domain.enums import AlertSeverity, AlertType
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from fastapi import FastAPI


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_jwt(*, role: str, service_name: str | None = None, sub: str = "service:test") -> str:
    """Build an unsigned-but-decodable JWT (skip_verification=True in test app).

    ``service_name`` is omitted when None so we can exercise the "system role
    but wrong/absent service_name" rejection path.
    """
    payload: dict[str, object] = {
        "sub": sub,
        "tenant_id": "tenant-test",
        "role": role,
        "iss": "worldview-gateway",
        "exp": 9999999999,
    }
    if service_name is not None:
        payload["service_name"] = service_name
    return jwt.encode(payload, "secret", algorithm="HS256")


def _allowed_headers() -> dict[str, str]:
    """Headers for the allow-listed brief-scheduler service identity."""
    return {
        "X-Internal-JWT": _make_jwt(
            role="system",
            service_name="rag-chat-brief-scheduler",
            sub="service:rag-chat-brief-scheduler",
        )
    }


def _fake_pair() -> tuple[PendingAlert, Alert]:
    """Build one (pending, alert) pair the use case would normally return."""
    alert = Alert(
        alert_type=AlertType.SIGNAL,
        severity=AlertSeverity.HIGH,
        source_topic="signals.v1",
        payload={"k": "v"},
        title="NVDA breakout",
        ticker="NVDA",
        entity_name="NVIDIA Corp",
        signal_label="price_breakout",
    )
    pending = PendingAlert(alert_id=alert.alert_id)
    return pending, alert


def _build_app(*, pairs: list[tuple[PendingAlert, Alert]]) -> FastAPI:
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
    # Minimal write-factory wiring so the app boots; unused by this read route.
    write_session = AsyncMock()
    write_session.__aenter__ = AsyncMock(return_value=write_session)
    write_session.__aexit__ = AsyncMock(return_value=False)
    app.state.session_factory = MagicMock(return_value=write_session)

    # Override the use case so we never touch the DB. ``execute`` ignores its
    # filter args here and returns the canned pairs — the route's auth guard and
    # response shape are what we're testing, not the SQL.
    fake_uc = MagicMock()
    fake_uc.execute = AsyncMock(return_value=pairs)
    app.dependency_overrides[get_pending_alerts_uc] = lambda: fake_uc
    return app


# ── Authorisation ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_listed_service_caller_returns_alerts() -> None:
    """role=system + allow-listed service_name → 200 with the alert payload."""
    user_id = uuid.uuid4()
    app = _build_app(pairs=[_fake_pair()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/alerts/pending",
            headers=_allowed_headers(),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["alerts"][0]["ticker"] == "NVDA"
    assert body["alerts"][0]["title"] == "NVDA breakout"


@pytest.mark.asyncio
async def test_normal_user_token_is_rejected_403() -> None:
    """A valid user token (role=user) must NOT read another user's alerts here."""
    user_id = uuid.uuid4()
    app = _build_app(pairs=[_fake_pair()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/alerts/pending",
            headers={"X-Internal-JWT": _make_jwt(role="user", sub=str(uuid.uuid4()))},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_system_role_unknown_service_name_is_rejected_403() -> None:
    """role=system but a service_name NOT on the allow-list → 403.

    Defence-in-depth: a leaked/foreign service token still cannot read alerts
    unless it is the exact brief-scheduler identity.
    """
    user_id = uuid.uuid4()
    app = _build_app(pairs=[_fake_pair()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/alerts/pending",
            headers={"X-Internal-JWT": _make_jwt(role="system", service_name="some-other-service")},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_missing_jwt_is_rejected() -> None:
    user_id = uuid.uuid4()
    app = _build_app(pairs=[_fake_pair()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(f"/internal/v1/users/{user_id}/alerts/pending")
    assert resp.status_code in (401, 403)


# ── Input validation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_min_severity_returns_422() -> None:
    user_id = uuid.uuid4()
    app = _build_app(pairs=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            f"/internal/v1/users/{user_id}/alerts/pending",
            params={"min_severity": "not-a-tier"},
            headers=_allowed_headers(),
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_user_id_returns_422() -> None:
    app = _build_app(pairs=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            "/internal/v1/users/not-a-uuid/alerts/pending",
            headers=_allowed_headers(),
        )
    assert resp.status_code == 422
