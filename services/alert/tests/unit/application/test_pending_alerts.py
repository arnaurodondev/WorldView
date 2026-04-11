"""Unit tests for GetPendingAlertsUseCase and AcknowledgeAlertUseCase.

Covers: constructor injection, min_severity SQL push (D-4), session commit on ack.

D-4 note: min_severity filtering is now pushed to SQL via min_severities parameter
on list_by_user(). The use case computes the min_severities list and passes it to
the repo. Tests verify:
  - correct min_severities are passed to the repo
  - no Python-side severity filtering happens in the use case
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
) -> tuple[GetPendingAlertsUseCase, AsyncMock]:
    """Return (use_case, mock_pending_repo) so callers can inspect repo calls."""
    mock_pending_repo = AsyncMock()
    mock_pending_repo.list_by_user = AsyncMock(return_value=pending_items)

    mock_alert_repo = AsyncMock()
    mock_alert_repo.get_by_id = AsyncMock(side_effect=lambda aid: alert_map.get(aid))

    uc = GetPendingAlertsUseCase(
        pending_repo=mock_pending_repo,  # type: ignore[arg-type]
        alert_repo=mock_alert_repo,  # type: ignore[arg-type]
    )
    return uc, mock_pending_repo


# ── GetPendingAlertsUseCase ───────────────────────────────────────────────────


class TestGetPendingAlertsUseCase:
    @pytest.mark.unit
    async def test_get_pending_no_min_severity(self) -> None:
        """Returns all pairs when min_severity is None; repo called with min_severities=None."""
        user_id = uuid4()
        alerts = [_make_alert(s) for s in (AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH)]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc, mock_repo = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0)

        assert len(pairs) == 3
        # The repo must be called with min_severities=None when no filter is set
        mock_repo.list_by_user.assert_awaited_once_with(user_id, limit=50, offset=0, min_severities=None)

    @pytest.mark.unit
    async def test_get_pending_min_severity_high_passes_correct_list(self) -> None:
        """min_severity=HIGH → repo receives min_severities=['high', 'critical'] (D-4)."""
        user_id = uuid4()
        high_alert = _make_alert(AlertSeverity.HIGH)
        critical_alert = _make_alert(AlertSeverity.CRITICAL)
        pendings = [_make_pending(user_id, a.alert_id) for a in (high_alert, critical_alert)]
        alert_map = {a.alert_id: a for a in (high_alert, critical_alert)}

        uc, mock_repo = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.HIGH)

        assert len(pairs) == 2
        # Verify the repo received the correct severities list — AlertSeverity is StrEnum
        # so str(AlertSeverity.HIGH) == "high", str(AlertSeverity.CRITICAL) == "critical"
        call_kwargs = mock_repo.list_by_user.call_args
        passed_severities: list[str] = call_kwargs.kwargs["min_severities"]
        assert set(passed_severities) == {"high", "critical"}

    @pytest.mark.unit
    async def test_get_pending_min_severity_critical_passes_correct_list(self) -> None:
        """min_severity=CRITICAL → repo receives min_severities=['critical']."""
        user_id = uuid4()
        critical_alert = _make_alert(AlertSeverity.CRITICAL)
        pendings = [_make_pending(user_id, critical_alert.alert_id)]
        alert_map = {critical_alert.alert_id: critical_alert}

        uc, mock_repo = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.CRITICAL)

        assert len(pairs) == 1
        assert pairs[0][1].severity == AlertSeverity.CRITICAL
        call_kwargs = mock_repo.list_by_user.call_args
        passed_severities: list[str] = call_kwargs.kwargs["min_severities"]
        assert passed_severities == ["critical"]

    @pytest.mark.unit
    async def test_get_pending_min_severity_low_passes_all_severities(self) -> None:
        """min_severity=LOW → repo receives all 4 severity values."""
        user_id = uuid4()
        alerts = [_make_alert(s) for s in AlertSeverity]
        pendings = [_make_pending(user_id, a.alert_id) for a in alerts]
        alert_map = {a.alert_id: a for a in alerts}

        uc, mock_repo = _make_get_uc(pendings, alert_map)
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.LOW)

        assert len(pairs) == len(alerts)
        call_kwargs = mock_repo.list_by_user.call_args
        passed_severities = call_kwargs.kwargs["min_severities"]
        # All 4 severities must be in the list
        assert passed_severities is not None
        assert len(passed_severities) == len(AlertSeverity)

    @pytest.mark.unit
    async def test_get_pending_empty_result_when_repo_returns_empty(self) -> None:
        """When repo returns [] (SQL filtered everything), use case returns []."""
        user_id = uuid4()

        uc, mock_repo = _make_get_uc([], {})
        # Simulate repo having filtered everything away at SQL level
        mock_repo.list_by_user = AsyncMock(return_value=[])
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.HIGH)

        assert pairs == []

    @pytest.mark.unit
    async def test_get_pending_no_python_side_severity_filter(self) -> None:
        """Use case does NOT filter pairs by severity after repo call (D-4 correctness)."""
        user_id = uuid4()
        # Mock repo returns LOW alerts even when a filter is set —
        # the use case must NOT apply a second Python-side filter.
        low_alert = _make_alert(AlertSeverity.LOW)
        pending = _make_pending(user_id, low_alert.alert_id)
        alert_map = {low_alert.alert_id: low_alert}

        uc, mock_repo = _make_get_uc([pending], alert_map)
        # Repo returns the LOW alert even though min_severity=HIGH was requested.
        # This simulates what happens when the filter is fully delegated to SQL
        # (use case must trust the repo's result and not re-filter).
        pairs = await uc.execute(user_id, limit=50, offset=0, min_severity=AlertSeverity.HIGH)

        # Use case should return whatever the repo gave — no second filter
        assert len(pairs) == 1


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
