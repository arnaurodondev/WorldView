"""Unit tests for PLAN-0049 T-A-1-03: alert title composition + signal_label fallback logging.

These tests pin the contract that:
  1. ``_compose_alert_title`` NEVER emits a bare ``"<SEVERITY> signal"`` string.
  2. The fanout use-case populates the new (title, ticker, entity_name, signal_label)
     enrichment columns on the persisted Alert.
  3. A ``signal_label_fallback`` warning is logged when claim_type/polarity are missing.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from alert.application.use_cases.alert_fanout import (
    AlertFanoutUseCase,
    _compose_alert_title,
    _derive_signal_label,
)
from alert.domain.enums import AlertSeverity, AlertType

# ─────────────────────────────────────────────────────────────────────────────
# _compose_alert_title — deterministic, no I/O
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestComposeAlertTitle:
    def test_uses_entity_name_and_signal_label_when_both_present(self) -> None:
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name="Apple Inc.",
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        assert title == "Apple Inc.: Bullish guidance"

    def test_falls_back_to_ticker_when_entity_name_missing(self) -> None:
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name=None,
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        assert title == "AAPL: Bullish guidance"

    def test_uses_signal_label_alone_when_no_entity_or_ticker(self) -> None:
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        assert title == "Bullish guidance"

    def test_humanises_alert_type_when_signal_label_is_fallback(self) -> None:
        # Fallback path with no entity / ticker — must NOT emit "LOW signal" form.
        title = _compose_alert_title(
            signal_label="LOW signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.GRAPH_CHANGE,
            is_signal_label_fallback=True,
        )
        # Humanised AlertType — never bare severity. Both "Graph Change Alert" and
        # "graph_change Alert" are acceptable depending on enum string form.
        assert title.endswith("alert")
        assert "signal" not in title.lower()

    def test_uses_entity_name_alone_when_fallback_label(self) -> None:
        title = _compose_alert_title(
            signal_label="HIGH signal",
            entity_name="Apple Inc.",
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        # Entity name is preferred over ticker; signal_label is suppressed (fallback case).
        assert title == "Apple Inc."

    def test_uses_ticker_alone_when_fallback_and_no_entity(self) -> None:
        title = _compose_alert_title(
            signal_label="HIGH signal",
            entity_name=None,
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        assert title == "AAPL"

    @pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    def test_never_outputs_bare_severity_signal_string(self, severity: str) -> None:
        """Regex-asserts the regression: F-D-006 / F-X-201."""
        title = _compose_alert_title(
            signal_label=f"{severity} signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        assert not re.fullmatch(
            r"(LOW|MEDIUM|HIGH|CRITICAL) signal", title
        ), f"composed title leaked bare-severity string: {title!r}"


# ─────────────────────────────────────────────────────────────────────────────
# _derive_signal_label — fallback flag contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDeriveSignalLabelFallbackFlag:
    def test_returns_false_flag_on_known_combo(self) -> None:
        label, is_fallback = _derive_signal_label(
            {"claim_type": "forward_guidance", "polarity": "positive"},
            AlertSeverity.LOW,
        )
        assert label == "Bullish guidance"
        assert is_fallback is False

    def test_returns_true_flag_on_missing_claim_type(self) -> None:
        label, is_fallback = _derive_signal_label({"polarity": "positive"}, AlertSeverity.MEDIUM)
        assert label == "MEDIUM signal"
        assert is_fallback is True

    def test_returns_true_flag_on_unknown_combination(self) -> None:
        label, is_fallback = _derive_signal_label(
            {"claim_type": "novel_unknown", "polarity": "neutral"},
            AlertSeverity.HIGH,
        )
        assert label == "HIGH signal"
        assert is_fallback is True


# ─────────────────────────────────────────────────────────────────────────────
# Integration with AlertFanoutUseCase — verify Alert persists enrichment fields
# ─────────────────────────────────────────────────────────────────────────────


_VALID_SIGNAL_EVENT: dict[str, Any] = {
    "event_id": "01951a96-7ec0-7000-8000-000000000001",
    "occurred_at": "2026-04-28T00:00:00Z",
    "event_type": "nlp.signal.detected",
    "schema_version": 2,
    # `_extract_entity_id` reads ``subject_entity_id`` for nlp.signal.detected.v1.
    "subject_entity_id": "01951a96-7ec0-7000-8000-000000000002",
    "tenant_id": "01951a96-7ec0-7000-8000-000000000003",
    "claim_type": "forward_guidance",
    "polarity": "positive",
    "signal_strength": 0.8,
    "market_impact_score": 0.7,
    "horizon_days": 7,
}


def _mock_session_factory(session: Any) -> Any:
    """Build a session_factory matching the ``async with`` protocol used by the use case."""
    sf = MagicMock()
    sf.return_value.__aenter__ = AsyncMock(return_value=session)
    sf.return_value.__aexit__ = AsyncMock(return_value=None)
    return sf


@pytest.mark.unit
@pytest.mark.asyncio
class TestAlertFanoutPopulatesEnrichmentFields:
    async def test_persists_title_ticker_entity_name_signal_label(self) -> None:
        saved: list[Any] = []
        alert_repo = AsyncMock()
        alert_repo.exists_by_dedup_key = AsyncMock(return_value=False)
        alert_repo.save = AsyncMock(side_effect=lambda a: saved.append(a))

        pending_repo = AsyncMock()
        dedup_repo = AsyncMock()
        dedup_repo.exists = AsyncMock(return_value=False)
        outbox_repo = AsyncMock()
        cache = AsyncMock()
        cache.get_subscribers_for_entity = AsyncMock(return_value=["01951a96-7ec0-7000-8000-000000000099"])
        ws_pub = AsyncMock()
        entity_resolver = AsyncMock()
        entity_resolver.resolve = AsyncMock(return_value=("Apple Inc.", "AAPL"))

        # ``await session.commit()`` and ``rollback()`` need awaitable mocks.
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        uc = AlertFanoutUseCase(
            session_factory=_mock_session_factory(session),
            watchlist_cache=cache,
            notification_publisher=ws_pub,
            repo_factory=lambda _s: (alert_repo, pending_repo, dedup_repo, outbox_repo),
            entity_resolver=entity_resolver,
        )

        await uc.execute(
            _VALID_SIGNAL_EVENT,
            "nlp.signal.detected.v1",
            market_impact_score=0.7,
        )

        assert saved, "alert was not saved"
        alert = saved[0]
        assert alert.signal_label == "Bullish guidance"
        assert alert.ticker == "AAPL"
        assert alert.entity_name == "Apple Inc."
        assert alert.title == "Apple Inc.: Bullish guidance"

    async def test_logs_warning_when_signal_label_falls_back(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Event missing claim_type → fallback path + warning log expected.
        event = dict(_VALID_SIGNAL_EVENT)
        del event["claim_type"]

        alert_repo = AsyncMock()
        alert_repo.exists_by_dedup_key = AsyncMock(return_value=False)
        alert_repo.save = AsyncMock()
        pending_repo = AsyncMock()
        dedup_repo = AsyncMock()
        dedup_repo.exists = AsyncMock(return_value=False)
        outbox_repo = AsyncMock()
        cache = AsyncMock()
        cache.get_subscribers_for_entity = AsyncMock(return_value=[])
        ws_pub = AsyncMock()
        entity_resolver = AsyncMock()
        entity_resolver.resolve = AsyncMock(return_value=(None, None))

        # ``await session.commit()`` and ``rollback()`` need awaitable mocks.
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        uc = AlertFanoutUseCase(
            session_factory=_mock_session_factory(session),
            watchlist_cache=cache,
            notification_publisher=ws_pub,
            repo_factory=lambda _s: (alert_repo, pending_repo, dedup_repo, outbox_repo),
            entity_resolver=entity_resolver,
        )

        await uc.execute(event, "nlp.signal.detected.v1", market_impact_score=0.5)

        # structlog ConsoleRenderer writes to stdout in this env; capture that.
        captured = capsys.readouterr()
        assert "signal_label_fallback" in (captured.out + captured.err)

    async def test_alert_title_never_bare_severity_after_full_fanout(self) -> None:
        """End-to-end: even with missing claim_type AND no entity resolver, title is humanised."""
        event = dict(_VALID_SIGNAL_EVENT)
        del event["claim_type"]

        saved: list[Any] = []
        alert_repo = AsyncMock()
        alert_repo.exists_by_dedup_key = AsyncMock(return_value=False)
        alert_repo.save = AsyncMock(side_effect=lambda a: saved.append(a))
        pending_repo = AsyncMock()
        dedup_repo = AsyncMock()
        dedup_repo.exists = AsyncMock(return_value=False)
        outbox_repo = AsyncMock()
        cache = AsyncMock()
        cache.get_subscribers_for_entity = AsyncMock(return_value=[])
        ws_pub = AsyncMock()

        # ``await session.commit()`` and ``rollback()`` need awaitable mocks.
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        uc = AlertFanoutUseCase(
            session_factory=_mock_session_factory(session),
            watchlist_cache=cache,
            notification_publisher=ws_pub,
            repo_factory=lambda _s: (alert_repo, pending_repo, dedup_repo, outbox_repo),
            entity_resolver=None,
        )

        await uc.execute(event, "nlp.signal.detected.v1", market_impact_score=0.5)

        assert saved, "alert not saved"
        title = saved[0].title
        assert title is not None
        assert not re.fullmatch(
            r"(LOW|MEDIUM|HIGH|CRITICAL) signal", title
        ), f"alert title leaked bare-severity string: {title!r}"
