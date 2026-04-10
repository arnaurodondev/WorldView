"""Unit tests for GetPendingAlertsUseCase and AcknowledgeAlertUseCase.

Covers: constructor injection, min_severity filtering, session commit on ack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.pending_alerts import (
    AcknowledgeAlertUseCase,
    GetPendingAlertsUseCase,
)
from alert.domain.entities import Alert, PendingAlert
from alert.domain.enums import AlertSeverity, AlertType

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_alert(severity: AlertSeverity = AlertSeverity.LOW) -> Alert:
    return Alert(
        alert_id=uuid4(),
        entity_id=uuid4(),
        alert_type=AlertType.SIGNAL,
        severity=severity,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={},
        dedup_key="abc",
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


def _make_get_uc(
    pending_items: list[PendingAlert],
    alert_map: dict[UUID, Alert | None],
) -> GetPendingAlertsUseCase:
    mock_pending_repo = AsyncMock()
    mock_pending_repo.list_by_user = AsyncMock(return_value=pending_items)

    mock_alert_repo = AsyncMock()
    mock_alert_repo.get_by_id = AsyncMock(side_effect=lambda aid: alert_map.get(aid))

    return GetPendingAlertsUseCase(
        pending_repo=mock_pending_repo,  # type: ignore[arg-type]
        alert_repo=mock_alert_repo,  # type: ignore[arg-type]
    )


# ── GetPendingAlertsUseCase ───────────────────────────────────────────────────


class TestGetPendingAlertsUseCase:
    @pytest.mark.unit
    async def test_get_pending_no_min_severity(self) -> None:
        """Returns all pairs when min_severity is None."""
        user_id = uuid4()
        alerts = [_make_alert(s) for s in (AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH)]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0)

        assert len(pairs) == 3

    @pytest.mark.unit
    async def test_get_pending_min_severity_high(self) -> None:
        """min_severity=HIGH filters out LOW and MEDIUM, keeps HIGH and CRITICAL."""
        user_id = uuid4()
        alerts = [
            _make_alert(AlertSeverity.LOW),
            _make_alert(AlertSeverity.MEDIUM),
            _make_alert(AlertSeverity.HIGH),
            _make_alert(AlertSeverity.CRITICAL),
        ]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.HIGH)

        severities = {a.severity for _, a in pairs}
        assert AlertSeverity.LOW not in severities
        assert AlertSeverity.MEDIUM not in severities
        assert AlertSeverity.HIGH in severities
        assert AlertSeverity.CRITICAL in severities
        assert len(pairs) == 2

    @pytest.mark.unit
    async def test_get_pending_min_severity_critical(self) -> None:
        """min_severity=CRITICAL keeps only CRITICAL alerts."""
        user_id = uuid4()
        alerts = [
            _make_alert(AlertSeverity.LOW),
            _make_alert(AlertSeverity.HIGH),
            _make_alert(AlertSeverity.CRITICAL),
        ]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.CRITICAL)

        assert len(pairs) == 1
        assert pairs[0][1].severity == AlertSeverity.CRITICAL

    @pytest.mark.unit
    async def test_get_pending_min_severity_low(self) -> None:
        """min_severity=LOW returns all (LOW is the minimum tier)."""
        user_id = uuid4()
        alerts = [_make_alert(s) for s in AlertSeverity]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.LOW)

        assert len(pairs) == len(alerts)

    @pytest.mark.unit
    async def test_get_pending_empty_after_filter(self) -> None:
        """All alerts below min_severity → returns empty list."""
        user_id = uuid4()
        alerts = [_make_alert(AlertSeverity.LOW), _make_alert(AlertSeverity.MEDIUM)]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.HIGH)

        assert pairs == []


# ── AcknowledgeAlertUseCase ───────────────────────────────────────────────────


class TestAcknowledgeAlertUseCase:
    @pytest.mark.unit
    async def test_acknowledge_commits_session(self) -> None:
        """execute() calls session.commit() when acknowledge() returns True."""
        user_id = uuid4()
        alert_id = uuid4()

        mock_pending_repo = AsyncMock()
        mock_pending_repo.acknowledge = AsyncMock(return_value=True)
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        uc = AcknowledgeAlertUseCase(
            pending_repo=mock_pending_repo,  # type: ignore[arg-type]
            session=mock_session,  # type: ignore[arg-type]
        )
        result = await uc.execute(user_id, alert_id)

        assert result is True
        mock_session.commit.assert_awaited_once()

    @pytest.mark.unit
    async def test_acknowledge_no_commit_on_failure(self) -> None:
        """execute() does NOT commit when acknowledge() returns False."""
        user_id = uuid4()
        alert_id = uuid4()

        mock_pending_repo = AsyncMock()
        mock_pending_repo.acknowledge = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        uc = AcknowledgeAlertUseCase(
            pending_repo=mock_pending_repo,  # type: ignore[arg-type]
            session=mock_session,  # type: ignore[arg-type]
        )
        result = await uc.execute(user_id, alert_id)

        assert result is False
        mock_session.commit.assert_not_called()
