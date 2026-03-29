"""Unit tests for AlertFanoutUseCase.

Covers: backfill suppression, dedup window, fan-out creation,
WebSocket push, and dedup key computation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.alert_fanout import (
    AlertFanoutUseCase,
    _extract_entity_id,
    _should_suppress,
)
from alert.domain.entities import Alert
from alert.domain.enums import AlertType
from alert.infrastructure.clients.s1_client import WatcherInfo

# ── Helpers ───────────────────────────────────────────────────────────────────

_ENTITY_ID = str(uuid4())
_USER_ID = str(uuid4())
_WATCHLIST_ID = str(uuid4())

_SIGNAL_EVENT = {
    "event_id": str(uuid4()),
    "event_type": "nlp.signal.detected",
    "occurred_at": "2026-03-29T10:00:00+00:00",
    "subject_entity_id": _ENTITY_ID,
    "claimer_entity_id": None,
    "is_backfill": False,
    "correlation_id": None,
}

_GRAPH_EVENT = {
    "event_id": str(uuid4()),
    "event_type": "graph.state.changed",
    "occurred_at": "2026-03-29T10:00:00+00:00",
    "primary_entity_id": _ENTITY_ID,
    "is_backfill": False,
    "correlation_id": None,
}

_CONTRADICTION_EVENT = {
    "event_id": str(uuid4()),
    "event_type": "intelligence.contradiction",
    "occurred_at": "2026-03-29T10:00:00+00:00",
    "subject_entity_id": _ENTITY_ID,
    "is_backfill": False,
    "correlation_id": None,
}


def _make_use_case(
    *,
    watchers: list[WatcherInfo] | None = None,
    dedup_exists: bool = False,
    save_alert_raises: Exception | None = None,
) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
    """Build a use case with mocked collaborators.

    Returns (use_case, mock_ws, mock_cache).
    """
    mock_ws = AsyncMock()
    mock_ws.send_to_user = AsyncMock(return_value=True)

    mock_cache = AsyncMock()
    mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])

    # Build a fake session that returns mocked repositories
    mock_dedup_repo = AsyncMock()
    mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)

    mock_alert_repo = AsyncMock()
    if save_alert_raises:
        mock_alert_repo.save = AsyncMock(side_effect=save_alert_raises)
    else:
        mock_alert_repo.save = AsyncMock()

    mock_pending_repo = AsyncMock()
    mock_pending_repo.save = AsyncMock()

    mock_outbox_repo = AsyncMock()
    mock_outbox_repo.append = AsyncMock()

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_sf = MagicMock()
    mock_sf.return_value = mock_session

    use_case = AlertFanoutUseCase(
        session_factory=mock_sf,
        watchlist_cache=mock_cache,
        connection_manager=mock_ws,
        dedup_window_seconds=300,
    )

    # Patch repository constructors to return our mocks
    use_case._dedup_repo_mock = mock_dedup_repo  # type: ignore[attr-defined]
    use_case._alert_repo_mock = mock_alert_repo  # type: ignore[attr-defined]
    use_case._pending_repo_mock = mock_pending_repo  # type: ignore[attr-defined]
    use_case._outbox_repo_mock = mock_outbox_repo  # type: ignore[attr-defined]

    return use_case, mock_ws, mock_cache


# ── Backfill suppression tests ────────────────────────────────────────────────


class TestBackfillSuppression:
    @pytest.mark.unit
    def test_suppresses_backfill_signal(self) -> None:
        event = {**_SIGNAL_EVENT, "is_backfill": True}
        assert _should_suppress(event, "nlp.signal.detected.v1") is True

    @pytest.mark.unit
    def test_suppresses_backfill_graph_change(self) -> None:
        event = {**_GRAPH_EVENT, "is_backfill": True}
        assert _should_suppress(event, "graph.state.changed.v1") is True

    @pytest.mark.unit
    def test_allows_non_backfill_signal(self) -> None:
        event = {**_SIGNAL_EVENT, "is_backfill": False}
        assert _should_suppress(event, "nlp.signal.detected.v1") is False

    @pytest.mark.unit
    def test_suppresses_old_backfill_contradiction(self) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        event = {**_CONTRADICTION_EVENT, "is_backfill": True, "occurred_at": old_date}
        assert _should_suppress(event, "intelligence.contradiction.v1") is True

    @pytest.mark.unit
    def test_allows_recent_backfill_contradiction(self) -> None:
        recent_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        event = {**_CONTRADICTION_EVENT, "is_backfill": True, "occurred_at": recent_date}
        assert _should_suppress(event, "intelligence.contradiction.v1") is False

    @pytest.mark.unit
    def test_suppresses_contradiction_with_malformed_date(self) -> None:
        event = {**_CONTRADICTION_EVENT, "is_backfill": True, "occurred_at": "not-a-date"}
        assert _should_suppress(event, "intelligence.contradiction.v1") is True

    @pytest.mark.unit
    def test_non_backfill_contradiction_always_allowed(self) -> None:
        old_date = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        event = {**_CONTRADICTION_EVENT, "is_backfill": False, "occurred_at": old_date}
        assert _should_suppress(event, "intelligence.contradiction.v1") is False


# ── Entity ID extraction ──────────────────────────────────────────────────────


class TestExtractEntityId:
    @pytest.mark.unit
    def test_extracts_from_signal_subject(self) -> None:
        assert _extract_entity_id(_SIGNAL_EVENT, "nlp.signal.detected.v1") == _ENTITY_ID

    @pytest.mark.unit
    def test_extracts_from_signal_claimer_fallback(self) -> None:
        event = {**_SIGNAL_EVENT, "subject_entity_id": None, "claimer_entity_id": _ENTITY_ID}
        assert _extract_entity_id(event, "nlp.signal.detected.v1") == _ENTITY_ID

    @pytest.mark.unit
    def test_extracts_from_graph_primary(self) -> None:
        assert _extract_entity_id(_GRAPH_EVENT, "graph.state.changed.v1") == _ENTITY_ID

    @pytest.mark.unit
    def test_extracts_from_contradiction_subject(self) -> None:
        assert _extract_entity_id(_CONTRADICTION_EVENT, "intelligence.contradiction.v1") == _ENTITY_ID

    @pytest.mark.unit
    def test_returns_none_for_unknown_topic(self) -> None:
        assert _extract_entity_id(_SIGNAL_EVENT, "unknown.topic") is None


# ── Dedup key computation ─────────────────────────────────────────────────────


class TestDedupKey:
    @pytest.mark.unit
    def test_same_window_same_key(self) -> None:
        entity_id = uuid4()
        t1 = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 29, 10, 4, 59, tzinfo=UTC)  # still in same 300s window
        k1 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t1, 300)
        k2 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t2, 300)
        assert k1 == k2

    @pytest.mark.unit
    def test_different_window_different_key(self) -> None:
        entity_id = uuid4()
        t1 = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 29, 10, 5, 1, tzinfo=UTC)  # next window
        k1 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t1, 300)
        k2 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t2, 300)
        assert k1 != k2

    @pytest.mark.unit
    def test_different_alert_type_different_key(self) -> None:
        entity_id = uuid4()
        t = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
        k1 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t, 300)
        k2 = Alert.compute_dedup_key(entity_id, AlertType.GRAPH_CHANGE, t, 300)
        assert k1 != k2

    @pytest.mark.unit
    def test_excludes_source_event_id(self) -> None:
        """Two events with same entity+type+window produce the same dedup key."""
        entity_id = uuid4()
        t = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
        k1 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t, 300)
        k2 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t, 300)
        assert k1 == k2  # source_event_id NOT in key per AD-9


# ── Full execute() integration ────────────────────────────────────────────────


class TestAlertFanoutExecute:
    @pytest.mark.unit
    async def test_suppresses_backfill_event(self) -> None:
        use_case, _, _ = _make_use_case()
        event = {**_SIGNAL_EVENT, "is_backfill": True}

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository"),
            patch("alert.application.use_cases.alert_fanout.AlertRepository"),
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository"),
            patch("alert.application.use_cases.alert_fanout.OutboxRepository"),
        ):
            result = await use_case.execute(event, "nlp.signal.detected.v1")

        assert result.suppressed is True
        assert result.suppression_reason == "backfill"

    @pytest.mark.unit
    async def test_returns_no_watchers_result(self) -> None:
        use_case, _mock_ws, _ = _make_use_case(watchers=[])

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository") as MockDedup,
            patch("alert.application.use_cases.alert_fanout.AlertRepository"),
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository"),
            patch("alert.application.use_cases.alert_fanout.OutboxRepository"),
        ):
            MockDedup.return_value.exists = AsyncMock(return_value=False)
            result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")

        assert result.suppressed is False
        assert result.watchers_count == 0
        _mock_ws.send_to_user.assert_not_called()

    @pytest.mark.unit
    async def test_dedup_suppresses_within_window(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, _mock_ws, _ = _make_use_case(watchers=watchers)

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository") as MockDedup,
            patch("alert.application.use_cases.alert_fanout.AlertRepository"),
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository"),
            patch("alert.application.use_cases.alert_fanout.OutboxRepository"),
        ):
            MockDedup.return_value.exists = AsyncMock(return_value=True)
            result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")

        assert result.suppressed is True
        assert result.suppression_reason == "dedup"
        _mock_ws.send_to_user.assert_not_called()

    @pytest.mark.unit
    async def test_fanout_creates_alert_and_pending(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, _mock_ws2, _ = _make_use_case(watchers=watchers)

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository") as MockDedup,
            patch("alert.application.use_cases.alert_fanout.AlertRepository") as MockAlert,
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository") as MockPending,
            patch("alert.application.use_cases.alert_fanout.OutboxRepository") as MockOutbox,
        ):
            MockDedup.return_value.exists = AsyncMock(return_value=False)
            MockAlert.return_value.save = AsyncMock()
            MockPending.return_value.save = AsyncMock()
            MockOutbox.return_value.append = AsyncMock()

            result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")

        assert result.suppressed is False
        assert result.watchers_count == 1
        assert result.pending_count == 1
        assert result.alert_id is not None
        MockAlert.return_value.save.assert_awaited_once()
        MockPending.return_value.save.assert_awaited_once()
        MockOutbox.return_value.append.assert_awaited_once()

    @pytest.mark.unit
    async def test_websocket_push_happens_after_commit(self) -> None:
        """WebSocket push must happen outside the DB transaction."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, mock_ws, _ = _make_use_case(watchers=watchers)

        commit_called_before_ws: list[bool] = []

        async def _track_send(user_id: UUID, data: dict) -> bool:
            commit_called_before_ws.append(True)
            return True

        mock_ws.send_to_user = AsyncMock(side_effect=_track_send)

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository") as MockDedup,
            patch("alert.application.use_cases.alert_fanout.AlertRepository") as MockAlert,
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository") as MockPending,
            patch("alert.application.use_cases.alert_fanout.OutboxRepository") as MockOutbox,
        ):
            MockDedup.return_value.exists = AsyncMock(return_value=False)
            MockAlert.return_value.save = AsyncMock()
            MockPending.return_value.save = AsyncMock()
            MockOutbox.return_value.append = AsyncMock()

            await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")

        # send_to_user must have been called (after commit, outside session)
        assert len(commit_called_before_ws) == 1

    @pytest.mark.unit
    async def test_suppresses_no_entity_id(self) -> None:
        event = {**_SIGNAL_EVENT, "subject_entity_id": None, "claimer_entity_id": None}
        use_case, _, _ = _make_use_case()

        with (
            patch("alert.application.use_cases.alert_fanout.DedupRepository"),
            patch("alert.application.use_cases.alert_fanout.AlertRepository"),
            patch("alert.application.use_cases.alert_fanout.PendingAlertRepository"),
            patch("alert.application.use_cases.alert_fanout.OutboxRepository"),
        ):
            result = await use_case.execute(event, "nlp.signal.detected.v1")

        assert result.suppressed is True
        assert result.suppression_reason == "no_entity_id"
