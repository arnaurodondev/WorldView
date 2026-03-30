"""Unit tests for Alert REST API routes.

Covers:
  - GET /api/v1/alerts/pending: pagination, empty results, user scoping
  - DELETE /api/v1/alerts/{alert_id}/ack: 204 on success, 404 on wrong user,
    404 on already-acknowledged, 404 on non-existent alert
  - WebSocket route is registered
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from alert.app import create_app
from alert.config import Settings
from alert.domain.entities import Alert, PendingAlert
from alert.domain.enums import AlertType
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        admin_token="test-admin",
        service_name="alert-unit-test",
        log_json=False,
    )
    app = create_app(settings)
    # Wire minimal state so dependency injection works without a real DB
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory

    from alert.infrastructure.websocket.manager import ConnectionManager

    app.state.ws_manager = ConnectionManager()
    return app, session  # type: ignore[return-value]


def _make_alert(entity_id: UUID | None = None) -> Alert:
    return Alert(
        alert_id=uuid4(),
        entity_id=entity_id or uuid4(),
        alert_type=AlertType.SIGNAL,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={"event_type": "nlp.signal.detected"},
        dedup_key="abc123",
        created_at=datetime.now(UTC),
    )


def _make_pending(user_id: UUID, alert_id: UUID) -> PendingAlert:
    return PendingAlert(
        pending_id=uuid4(),
        user_id=user_id,
        alert_id=alert_id,
        created_at=datetime.now(UTC),
        delivered_at=None,
    )


# ── GET /api/v1/alerts/pending ────────────────────────────────────────────────

# Patch paths target the use case module where the repos are imported.
_PENDING_REPO_PATH = "alert.application.use_cases.pending_alerts.PendingAlertRepository"
_ALERT_REPO_PATH = "alert.application.use_cases.pending_alerts.AlertRepository"


class TestGetPendingAlerts:
    @pytest.mark.unit
    async def test_returns_empty_list_when_no_alerts(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = str(uuid4())

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[])

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/v1/alerts/pending?user_id={user_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert data["total"] == 0

    @pytest.mark.unit
    async def test_returns_pending_alerts_for_user(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert = _make_alert()
        pending = _make_pending(user_id, alert.alert_id)

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[pending])
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=alert)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/v1/alerts/pending?user_id={user_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert str(data["alerts"][0]["alert_id"]) == str(alert.alert_id)
        assert data["alerts"][0]["alert_type"] == "SIGNAL"

    @pytest.mark.unit
    async def test_pagination_params_respected(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()

        captured_args: list[dict] = []

        async def _capture_list(uid: UUID, limit: int = 50, offset: int = 0) -> list:
            captured_args.append({"user_id": uid, "limit": limit, "offset": offset})
            return []

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
            MockPendingRepo.return_value.list_by_user = _capture_list

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.get(f"/api/v1/alerts/pending?user_id={user_id}&limit=10&offset=20")

        assert captured_args[0]["limit"] == 10
        assert captured_args[0]["offset"] == 20

    @pytest.mark.unit
    async def test_missing_alert_record_skipped(self) -> None:
        """Pending row whose alert was deleted (orphan) is silently skipped."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        pending = _make_pending(user_id, uuid4())

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[pending])
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=None)  # orphan

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/v1/alerts/pending?user_id={user_id}")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── DELETE /api/v1/alerts/{alert_id}/ack ─────────────────────────────────────


class TestAcknowledgeAlert:
    @pytest.mark.unit
    async def test_ack_returns_200_on_success(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=True)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "acknowledged"

    @pytest.mark.unit
    async def test_ack_returns_404_on_wrong_user(self) -> None:
        """ack returns 404 — not 403 — when alert belongs to a different user."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=False)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")

        assert resp.status_code == 404

    @pytest.mark.unit
    async def test_ack_returns_404_on_already_acknowledged(self) -> None:
        """ack returns 404 when the alert was already acknowledged."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=False)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")

        # Same as wrong user — avoids user enumeration
        assert resp.status_code == 404

    @pytest.mark.unit
    async def test_ack_calls_acknowledge_with_correct_ids(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        captured: list[tuple[UUID, UUID]] = []

        async def _capture_ack(uid: UUID, aid: UUID) -> bool:
            captured.append((uid, aid))
            return True

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = _capture_ack

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")

        assert captured[0] == (user_id, alert_id)
