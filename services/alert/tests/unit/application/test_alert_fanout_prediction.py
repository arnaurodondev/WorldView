"""Unit tests for AlertFanoutUseCase — prediction signal path (PLAN-0056 Wave D3).

Covers: entity extraction from the prediction topic, watchlist gating (watched →
alert created; unwatched → suppressed), severity derived from market_impact_score
(NOT the MEDIUM override), payload carry of trigger/polarity/market_id/question/url,
and adverse (bearish) vs favorable (bullish) title copy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alert.application.use_cases.alert_fanout import (
    AlertFanoutUseCase,
    _compose_prediction_detail,
    _extract_entity_id,
)
from alert.domain.enums import AlertSeverity, AlertType
from alert.infrastructure.clients.s1_client import WatcherInfo

if TYPE_CHECKING:
    from alert.domain.entities import Alert

pytestmark = pytest.mark.unit

_PREDICTION_TOPIC = "market.prediction.signal.v1"
_ENTITY_ID = str(uuid4())
_USER_ID = str(uuid4())
_WATCHLIST_ID = str(uuid4())


def _prediction_event(**overrides: object) -> dict:
    base = {
        "event_id": str(uuid4()),
        "event_type": "market.prediction.signal",
        "occurred_at": "2026-07-09T10:00:00+00:00",
        "subject_entity_id": _ENTITY_ID,
        "market_id": "0xcondition-abc",
        "trigger": "material_move",
        "polarity": "bearish",
        "market_impact_score": 0.72,
        "question": "Will ACME miss Q3 guidance?",
        "url": "https://polymarket.com/event/acme-guidance",
        "is_backfill": False,
        "correlation_id": None,
    }
    base.update(overrides)
    return base


def _make_use_case(
    *,
    watchers: list[WatcherInfo] | None = None,
    saved_alerts: list[Alert] | None = None,
) -> AlertFanoutUseCase:
    mock_ws = AsyncMock()
    mock_ws.send_to_user = AsyncMock(return_value=True)
    mock_cache = AsyncMock()
    mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])

    mock_dedup_repo = AsyncMock()
    mock_dedup_repo.exists = AsyncMock(return_value=False)
    mock_alert_repo = AsyncMock()
    if saved_alerts is not None:
        mock_alert_repo.save = AsyncMock(side_effect=lambda a: saved_alerts.append(a))
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

    def _repo_factory(_s):  # type: ignore[no-untyped-def]
        return mock_alert_repo, mock_pending_repo, mock_dedup_repo, mock_outbox_repo

    return AlertFanoutUseCase(
        session_factory=mock_sf,
        watchlist_cache=mock_cache,
        notification_publisher=mock_ws,
        repo_factory=_repo_factory,
    )


# ── Entity extraction ─────────────────────────────────────────────────────────


class TestPredictionEntityExtraction:
    @pytest.mark.unit
    def test_extracts_subject_entity_id(self) -> None:
        assert _extract_entity_id(_prediction_event(), _PREDICTION_TOPIC) == _ENTITY_ID

    @pytest.mark.unit
    def test_returns_none_without_subject(self) -> None:
        event = _prediction_event(subject_entity_id=None)
        assert _extract_entity_id(event, _PREDICTION_TOPIC) is None


# ── Watchlist gating + severity ───────────────────────────────────────────────


class TestPredictionFanout:
    @pytest.mark.unit
    async def test_watched_entity_creates_prediction_alert(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_use_case(watchers=watchers, saved_alerts=saved)

        result = await uc.execute(_prediction_event(), _PREDICTION_TOPIC, market_impact_score=0.72)

        assert result.suppressed is False
        assert result.alert_id is not None
        assert len(saved) == 1
        alert = saved[0]
        assert alert.alert_type == AlertType.PREDICTION
        assert alert.dedup_key  # non-empty
        # Severity from score (0.72 → HIGH via default thresholds), NOT MEDIUM override.
        assert alert.severity == AlertSeverity.HIGH

    @pytest.mark.unit
    async def test_unwatched_entity_suppressed(self) -> None:
        uc = _make_use_case(watchers=[])
        result = await uc.execute(_prediction_event(), _PREDICTION_TOPIC, market_impact_score=0.72)
        assert result.suppressed is False  # not suppressed, just no watchers
        assert result.watchers_count == 0
        assert result.alert_id is None

    @pytest.mark.unit
    async def test_critical_score_maps_to_critical(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_use_case(watchers=watchers, saved_alerts=saved)
        await uc.execute(_prediction_event(), _PREDICTION_TOPIC, market_impact_score=0.90)
        assert saved[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.unit
    async def test_payload_carries_prediction_fields(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_use_case(watchers=watchers, saved_alerts=saved)
        await uc.execute(_prediction_event(), _PREDICTION_TOPIC, market_impact_score=0.72)
        payload = saved[0].payload
        assert payload["market_id"] == "0xcondition-abc"
        assert payload["polarity"] == "bearish"
        assert payload["trigger"] == "material_move"
        assert payload["question"] == "Will ACME miss Q3 guidance?"
        assert payload["url"] == "https://polymarket.com/event/acme-guidance"

    @pytest.mark.unit
    async def test_bearish_title_reads_as_risk_against_entity(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_use_case(watchers=watchers, saved_alerts=saved)
        await uc.execute(_prediction_event(polarity="bearish"), _PREDICTION_TOPIC, market_impact_score=0.72)
        assert "against" in saved[0].title  # type: ignore[operator]

    @pytest.mark.unit
    async def test_bullish_title_reads_favorably(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_use_case(watchers=watchers, saved_alerts=saved)
        await uc.execute(_prediction_event(polarity="bullish"), _PREDICTION_TOPIC, market_impact_score=0.72)
        title = saved[0].title or ""
        assert "in favor of" in title
        assert "against" not in title


# ── Detail composition (pure) ─────────────────────────────────────────────────


class TestPredictionDetail:
    @pytest.mark.unit
    def test_bearish_material_move(self) -> None:
        detail = _compose_prediction_detail(_prediction_event(polarity="bearish", trigger="material_move"))
        assert detail.startswith("prediction market moving against")

    @pytest.mark.unit
    def test_neutral_has_no_direction(self) -> None:
        detail = _compose_prediction_detail(_prediction_event(polarity="neutral", trigger="new_market"))
        assert "against" not in detail
        assert "in favor of" not in detail
        assert detail.startswith("new prediction market")

    @pytest.mark.unit
    def test_missing_fields_fall_back(self) -> None:
        detail = _compose_prediction_detail({})
        assert detail == "prediction market update"

    @pytest.mark.unit
    def test_long_question_truncated(self) -> None:
        long_q = "Will the company " + "x" * 200 + " happen?"
        detail = _compose_prediction_detail(_prediction_event(question=long_q))
        assert detail.endswith("...")
        assert len(detail) < len(long_q)


# ── Dedup key: distinct markets must NOT collapse (PLAN-0056 QA FIX 3) ─────────


def _make_stateful_use_case(
    *,
    watchers: list[WatcherInfo],
    saved_alerts: list[Alert],
) -> AlertFanoutUseCase:
    """Build a use case whose dedup repo is STATEFUL across ``execute`` calls.

    ``dedup_repo.exists(key)`` returns True once an alert with that ``dedup_key``
    has been saved — mirroring the production DB unique-constraint gate. This lets
    a test assert the real collapse/split behaviour end-to-end rather than only at
    the pure ``compute_dedup_key`` level.
    """
    seen_keys: set[str] = set()

    mock_ws = AsyncMock()
    mock_ws.send_to_user = AsyncMock(return_value=True)
    mock_cache = AsyncMock()
    mock_cache.get_watchers = AsyncMock(return_value=watchers)

    mock_dedup_repo = AsyncMock()
    mock_dedup_repo.exists = AsyncMock(side_effect=lambda key: key in seen_keys)

    mock_alert_repo = AsyncMock()

    def _save(alert: Alert) -> None:
        seen_keys.add(alert.dedup_key)
        saved_alerts.append(alert)

    mock_alert_repo.save = AsyncMock(side_effect=_save)
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

    return AlertFanoutUseCase(
        session_factory=mock_sf,
        watchlist_cache=mock_cache,
        notification_publisher=mock_ws,
        repo_factory=_repo_factory,
    )


class TestPredictionDedupKey:
    @pytest.mark.unit
    async def test_two_distinct_markets_same_entity_same_window_yield_two_alerts(self) -> None:
        """Two DISTINCT prediction markets on the SAME entity in one 300s window
        must each raise their own alert — market_id splits the dedup bucket."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_stateful_use_case(watchers=watchers, saved_alerts=saved)

        # Same entity + same occurred_at (same window bucket), different markets.
        ev_a = _prediction_event(market_id="0xcondition-AAA", event_id=str(uuid4()))
        ev_b = _prediction_event(market_id="0xcondition-BBB", event_id=str(uuid4()))
        await uc.execute(ev_a, _PREDICTION_TOPIC, market_impact_score=0.72)
        await uc.execute(ev_b, _PREDICTION_TOPIC, market_impact_score=0.72)

        assert len(saved) == 2
        assert saved[0].dedup_key != saved[1].dedup_key

    @pytest.mark.unit
    async def test_same_market_repeated_move_same_window_is_deduped(self) -> None:
        """Repeated moves on the SAME market within one window still collapse
        (per-market cooldown preserved) — one alert, second suppressed."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_stateful_use_case(watchers=watchers, saved_alerts=saved)

        ev1 = _prediction_event(market_id="0xcondition-SAME", event_id=str(uuid4()))
        ev2 = _prediction_event(market_id="0xcondition-SAME", event_id=str(uuid4()))
        await uc.execute(ev1, _PREDICTION_TOPIC, market_impact_score=0.72)
        result2 = await uc.execute(ev2, _PREDICTION_TOPIC, market_impact_score=0.72)

        assert len(saved) == 1
        assert result2.suppressed is True
        assert result2.suppression_reason == "dedup"

    @pytest.mark.unit
    async def test_different_trigger_same_market_splits(self) -> None:
        """Distinct triggers on the same market also split the bucket so a
        new-market signal and a material-move signal don't suppress each other."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
        saved: list[Alert] = []
        uc = _make_stateful_use_case(watchers=watchers, saved_alerts=saved)

        ev1 = _prediction_event(market_id="0xc", trigger="new_market", event_id=str(uuid4()))
        ev2 = _prediction_event(market_id="0xc", trigger="material_move", event_id=str(uuid4()))
        await uc.execute(ev1, _PREDICTION_TOPIC, market_impact_score=0.72)
        await uc.execute(ev2, _PREDICTION_TOPIC, market_impact_score=0.72)

        assert len(saved) == 2


class TestComputeDedupKeyDiscriminator:
    @pytest.mark.unit
    def test_discriminator_changes_key(self) -> None:
        from datetime import UTC, datetime

        from alert.domain.entities import Alert

        entity_id = uuid4()
        ts = datetime(2026, 7, 9, 10, 0, 0, tzinfo=UTC)
        key_a = Alert.compute_dedup_key(entity_id, AlertType.PREDICTION, ts, discriminator="0xAAA:material_move")
        key_b = Alert.compute_dedup_key(entity_id, AlertType.PREDICTION, ts, discriminator="0xBBB:material_move")
        assert key_a != key_b

    @pytest.mark.unit
    def test_no_discriminator_matches_legacy_key(self) -> None:
        """discriminator=None must reproduce the historical per-entity+type key so
        SIGNAL/GRAPH/CONTRADICTION collapse behaviour is unchanged."""
        from datetime import UTC, datetime

        from alert.domain.entities import Alert

        entity_id = uuid4()
        ts = datetime(2026, 7, 9, 10, 0, 0, tzinfo=UTC)
        legacy = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, ts)
        with_none = Alert.compute_dedup_key(entity_id, AlertType.SIGNAL, ts, discriminator=None)
        assert legacy == with_none
