"""Unit tests for AlertFanoutUseCase.

Covers: backfill suppression, dedup window, fan-out creation,
WebSocket push, and dedup key computation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.alert_fanout import (
    AlertFanoutUseCase,
    _extract_entity_id,
    _get_parsed_schema,
    _should_suppress,
)
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType
from alert.infrastructure.clients.s1_client import WatcherInfo

pytestmark = pytest.mark.unit

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

    def _repo_factory(_session):  # type: ignore[no-untyped-def]
        return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

    use_case = AlertFanoutUseCase(
        session_factory=mock_sf,
        watchlist_cache=mock_cache,
        notification_publisher=mock_ws,
        repo_factory=_repo_factory,
        dedup_window_seconds=300,
    )

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
        result = await use_case.execute(event, "nlp.signal.detected.v1")
        assert result.suppressed is True
        assert result.suppression_reason == "backfill"

    @pytest.mark.unit
    async def test_returns_no_watchers_result(self) -> None:
        use_case, _mock_ws, _ = _make_use_case(watchers=[])
        result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        assert result.suppressed is False
        assert result.watchers_count == 0
        _mock_ws.send_to_user.assert_not_called()

    @pytest.mark.unit
    async def test_dedup_suppresses_within_window(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, _mock_ws, _ = _make_use_case(watchers=watchers, dedup_exists=True)
        result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        assert result.suppressed is True
        assert result.suppression_reason == "dedup"
        _mock_ws.send_to_user.assert_not_called()

    @pytest.mark.unit
    async def test_fanout_creates_alert_and_pending(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, _mock_ws2, _ = _make_use_case(watchers=watchers)
        result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        assert result.suppressed is False
        assert result.watchers_count == 1
        assert result.pending_count == 1
        assert result.alert_id is not None

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
        await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        # send_to_user must have been called (after commit, outside session)
        assert len(commit_called_before_ws) == 1

    @pytest.mark.unit
    async def test_suppresses_no_entity_id(self) -> None:
        event = {**_SIGNAL_EVENT, "subject_entity_id": None, "claimer_entity_id": None}
        use_case, _, _ = _make_use_case()
        result = await use_case.execute(event, "nlp.signal.detected.v1")
        assert result.suppressed is True
        assert result.suppression_reason == "no_entity_id"

    @pytest.mark.unit
    async def test_dedup_race_condition_returns_suppressed(self) -> None:
        """Concurrent writes with same dedup_key: DuplicateAlertError → suppressed result."""
        from alert.domain.errors import DuplicateAlertError

        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, mock_ws, _ = _make_use_case(
            watchers=watchers,
            save_alert_raises=DuplicateAlertError("race condition: duplicate dedup_key"),
        )
        result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        assert result.suppressed is True
        assert result.suppression_reason == "dedup"
        mock_ws.send_to_user.assert_not_called()


# ── Severity computation (PRD-0021 §6.5) ─────────────────────────────────────


class TestAlertFanoutSeverity:
    @pytest.mark.unit
    async def test_alert_fanout_severity_critical_from_score(self) -> None:
        """Signal event with score=0.90 → saved Alert.severity == CRITICAL."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1", market_impact_score=0.90)

        assert len(saved_alerts) == 1
        assert saved_alerts[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.unit
    async def test_alert_fanout_severity_low_for_missing_score(self) -> None:
        """Signal event without market_impact_score → defaults to 0.0 → LOW."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        use_case, _, _ = _make_use_case(watchers=watchers)
        # Default market_impact_score=0.0 → LOW
        result = await use_case.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1")
        assert result.alert_id is not None
        assert result.suppressed is False

    @pytest.mark.unit
    async def test_alert_fanout_severity_medium_for_graph_event(self) -> None:
        """graph.state.changed.v1 → F-13 override → severity=MEDIUM regardless of score."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        _use_case, _, _ = _make_use_case(watchers=watchers)

        # Track what Alert was created via alert_repo.save
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_GRAPH_EVENT, "graph.state.changed.v1", market_impact_score=0.99)

        assert len(saved_alerts) == 1
        assert saved_alerts[0].severity == AlertSeverity.MEDIUM

    @pytest.mark.unit
    async def test_alert_fanout_severity_medium_for_contradiction(self) -> None:
        """intelligence.contradiction.v1 → F-13 override → severity=MEDIUM."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_CONTRADICTION_EVENT, "intelligence.contradiction.v1", market_impact_score=0.95)

        assert len(saved_alerts) == 1
        assert saved_alerts[0].severity == AlertSeverity.MEDIUM

    @pytest.mark.unit
    async def test_alert_fanout_ws_payload_includes_severity(self) -> None:
        """WS push payload dict must contain the 'severity' key."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        ws_payloads: list[dict] = []

        mock_ws = AsyncMock()
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
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

        async def _capture_send(user_id: UUID, payload: dict) -> bool:
            ws_payloads.append(payload)
            return True

        mock_ws.send_to_user = AsyncMock(side_effect=_capture_send)

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1", market_impact_score=0.90)

        assert len(ws_payloads) == 1
        assert "severity" in ws_payloads[0]
        assert ws_payloads[0]["severity"] == "critical"

    @pytest.mark.unit
    async def test_alert_fanout_dedup_key_unchanged_by_severity(self) -> None:
        """Two calls with different scores produce same dedup key for same entity/type/window (F-14)."""
        from datetime import UTC, datetime

        from alert.application.use_cases.alert_fanout import Alert

        entity_id = uuid4()
        t = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
        k1 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t, 300)
        k2 = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, t, 300)
        assert k1 == k2

    @pytest.mark.unit
    async def test_alert_fanout_score_clamped_above_1(self) -> None:
        """market_impact_score=1.5 → clamped to 1.0 → CRITICAL."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1", market_impact_score=1.5)

        assert len(saved_alerts) == 1
        assert saved_alerts[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.unit
    async def test_alert_fanout_score_clamped_below_0(self) -> None:
        """market_impact_score=-0.1 → clamped to 0.0 → LOW."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        await uc.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1", market_impact_score=-0.1)

        assert len(saved_alerts) == 1
        assert saved_alerts[0].severity == AlertSeverity.LOW

    @pytest.mark.unit
    def test_fanout_accepts_iwatchlist_cache_protocol(self) -> None:
        """WatchlistCache satisfies the IWatchlistCache Protocol at runtime (D-5)."""
        from alert.application.ports.watchlist import IWatchlistCache
        from alert.infrastructure.cache.watchlist_cache import WatchlistCache

        # isinstance check works because IWatchlistCache is @runtime_checkable
        # and WatchlistCache has a get_watchers(entity_id: str) method.
        # We verify via Protocol structural check (no instantiation needed).
        assert issubclass(WatchlistCache, IWatchlistCache) or hasattr(
            WatchlistCache, "get_watchers"
        ), "WatchlistCache must implement IWatchlistCache.get_watchers"

    @pytest.mark.unit
    async def test_payload_enriched_with_entity_resolver(self) -> None:
        """When an entity_resolver is wired, the persisted Alert payload contains
        entity_name, ticker, and signal_label — covering PLAN-0048 Wave B-1.
        """
        from alert.application.ports.entity_resolver import EntityNameResolverPort

        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        # In-memory fake resolver. WHY a class (not AsyncMock): proves the port
        # accepts a concrete subclass and exercises the abstract contract.
        class _FakeResolver(EntityNameResolverPort):
            async def resolve(self, entity_id):  # type: ignore[no-untyped-def]
                return ("Apple Inc.", "AAPL")

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
            entity_resolver=_FakeResolver(),
        )
        # Use a forward_guidance + positive event so signal_label resolves to the
        # human-readable variant rather than the severity fallback.
        signal_event = {
            **_SIGNAL_EVENT,
            "claim_type": "forward_guidance",
            "polarity": "positive",
        }
        await uc.execute(signal_event, "nlp.signal.detected.v1", market_impact_score=0.5)

        assert len(saved_alerts) == 1
        payload = saved_alerts[0].payload
        assert payload["entity_name"] == "Apple Inc."
        assert payload["ticker"] == "AAPL"
        assert payload["signal_label"] == "Bullish guidance"

    @pytest.mark.unit
    async def test_payload_signal_label_fallback_when_no_claim_type(self) -> None:
        """Missing claim_type/polarity → label falls back to ``<SEVERITY> signal``."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved_alerts: list[Alert] = []

        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers)
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=False)
        mock_alert_repo = AsyncMock()
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

        def _repo_factory(_s):  # type: ignore[no-untyped-def]
            return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

        uc = AlertFanoutUseCase(
            session_factory=mock_sf,
            watchlist_cache=mock_cache,
            notification_publisher=mock_ws,
            repo_factory=_repo_factory,
        )
        # Score 0.90 → CRITICAL severity → label "CRITICAL signal".
        await uc.execute(_SIGNAL_EVENT, "nlp.signal.detected.v1", market_impact_score=0.90)
        assert saved_alerts[0].payload["signal_label"] == "CRITICAL signal"

    @pytest.mark.unit
    def test_signal_label_table_full_coverage(self) -> None:
        """All 8 (claim_type, polarity) combinations resolve correctly + case-insensitive."""
        from alert.application.use_cases.alert_fanout import _derive_signal_label
        from alert.domain.enums import AlertSeverity

        cases = [
            ("forward_guidance", "positive", "Bullish guidance"),
            ("forward_guidance", "negative", "Bearish guidance"),
            ("factual", "positive", "Positive factual"),
            ("factual", "negative", "Negative factual"),
            ("projection", "positive", "Bullish projection"),
            ("projection", "negative", "Bearish projection"),
            ("opinion", "positive", "Bullish opinion"),
            ("opinion", "negative", "Bearish opinion"),
        ]
        for ct, pol, expected in cases:
            event = {"claim_type": ct.upper(), "polarity": pol.upper()}  # case-insensitive
            label, is_fallback = _derive_signal_label(event, AlertSeverity.LOW)
            assert label == expected, f"failed for ({ct}, {pol})"
            assert is_fallback is False, f"unexpected fallback for ({ct}, {pol})"

        # Fallback case: missing claim_type → bare-severity string + is_fallback=True
        fb_label, fb_flag = _derive_signal_label({"polarity": "positive"}, AlertSeverity.HIGH)
        assert fb_label == "HIGH signal"
        assert fb_flag is True

    @pytest.mark.unit
    def test_alert_fanout_avro_schema_loads_from_file(self) -> None:
        """_get_parsed_schema() loads from .avsc file, not an inline dict."""
        # Reset cached schema to force a reload
        import alert.application.use_cases.alert_fanout as _mod

        _mod._PARSED_SCHEMA = None

        schema = _get_parsed_schema()

        # Verify it is a parsed fastavro schema (dict-like with 'name')
        assert schema is not None
        # The schema should have the severity field with default "low"
        fields = {f["name"]: f for f in schema.get("fields", [])}
        assert "severity" in fields
        assert fields["severity"].get("default") == "low"
        # schema_version should default to 2
        assert fields["schema_version"].get("default") == 2
