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
    _compose_graph_change_detail,
    _derive_signal_label,
    _humanise_relation_counts,
)
from alert.domain.enums import AlertSeverity, AlertType

pytestmark = pytest.mark.unit

# ─────────────────────────────────────────────────────────────────────────────
# _compose_alert_title — deterministic, no I/O
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestComposeAlertTitle:
    def test_uses_ticker_and_signal_label_when_both_present(self) -> None:
        # PLAN-0053 T-A-1-06: ticker takes priority over entity_name in the
        # subject resolver. Rationale: in a finance terminal context "AAPL:
        # Bullish guidance" matches Bloomberg convention; full company names
        # are reserved for tooltips and detail panels.
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name="Apple Inc.",
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        # Wave-4 clarity upgrade: subject and detail are now joined with an
        # em-dash ("AAPL — Bullish guidance") matching the target UX, replacing
        # the old colon separator.
        assert title == "AAPL — Bullish guidance"

    def test_falls_back_to_ticker_when_entity_name_missing(self) -> None:
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name=None,
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        assert title == "AAPL — Bullish guidance"

    def test_uses_signal_label_alone_when_no_entity_or_ticker(self) -> None:
        title = _compose_alert_title(
            signal_label="Bullish guidance",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=False,
        )
        assert title == "Bullish guidance"

    # PLAN-0053 T-A-1-06: per-AlertType templates replace the old humanise
    # fallback. GRAPH_CHANGE / CONTRADICTION never had NLP context (claim_type/
    # polarity) so the old code emitted "Graph Change alert" — meaningless to
    # users. New behavior: explicit per-type templates.

    def test_graph_change_no_subject_uses_template(self) -> None:
        title = _compose_alert_title(
            signal_label="LOW signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.GRAPH_CHANGE,
            is_signal_label_fallback=True,
        )
        assert title == "Graph pattern change"
        assert "alert" not in title.lower()

    def test_graph_change_with_ticker_no_event_uses_template(self) -> None:
        # When no raw event is passed (legacy / minimal callers), GRAPH_CHANGE
        # degrades to the static template prefixed by the subject + em-dash.
        title = _compose_alert_title(
            signal_label="LOW signal",
            entity_name=None,
            ticker="SPY",
            alert_type=AlertType.GRAPH_CHANGE,
            is_signal_label_fallback=True,
        )
        assert title == "SPY — graph pattern change"

    def test_contradiction_with_entity_name(self) -> None:
        title = _compose_alert_title(
            signal_label="HIGH signal",
            entity_name="Apple Inc.",
            ticker=None,
            alert_type=AlertType.CONTRADICTION,
            is_signal_label_fallback=True,
        )
        assert title == "Apple Inc. — conflicting signals"

    def test_contradiction_no_subject(self) -> None:
        title = _compose_alert_title(
            signal_label="LOW signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.CONTRADICTION,
            is_signal_label_fallback=True,
        )
        assert title == "Conflicting signals"

    def test_signal_fallback_with_entity_uses_signal_template(self) -> None:
        # SIGNAL with no claim_type/polarity but entity available — emit a
        # contextual "<subject> — price signal detected" instead of bare name.
        title = _compose_alert_title(
            signal_label="HIGH signal",
            entity_name="Apple Inc.",
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        # ticker takes priority over entity_name in the subject resolver.
        assert title == "AAPL — price signal detected"

    def test_signal_fallback_with_ticker_only(self) -> None:
        title = _compose_alert_title(
            signal_label="HIGH signal",
            entity_name=None,
            ticker="AAPL",
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        assert title == "AAPL — price signal detected"

    def test_signal_fallback_no_subject(self) -> None:
        title = _compose_alert_title(
            signal_label="LOW signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.SIGNAL,
            is_signal_label_fallback=True,
        )
        assert title == "Signal detected"

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
# Graph-change humanisation (Wave-4 alert-title clarity)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHumaniseRelationCounts:
    def test_empty_returns_empty_string(self) -> None:
        assert _humanise_relation_counts([]) == ""

    def test_single_type_singular_count(self) -> None:
        assert _humanise_relation_counts(["supplier_of"]) == "1 supplier"

    def test_counts_and_orders_by_frequency(self) -> None:
        # 5 supplier_of, 4 competes_with → most frequent first.
        types = ["supplier_of"] * 5 + ["competes_with"] * 4
        assert _humanise_relation_counts(types) == "5 supplier, 4 competitor"

    def test_collapses_synonyms(self) -> None:
        # has_executive + appointed_as both humanise to "executive".
        assert _humanise_relation_counts(["has_executive", "appointed_as"]) == "2 executive"

    def test_unknown_type_falls_back_to_link(self) -> None:
        assert _humanise_relation_counts(["totally_unknown_rel"]) == "1 link"

    def test_caps_at_three_categories_with_more_suffix(self) -> None:
        types = ["supplier_of", "competes_with", "partner_of", "owns_stake_in", "listed_on"]
        out = _humanise_relation_counts(types)
        # 3 named categories + "+N more" tail.
        assert out.count(",") == 3
        assert out.endswith("more")


@pytest.mark.unit
class TestComposeGraphChangeDetail:
    def test_real_live_event_shape(self) -> None:
        # Mirrors live AAPL graph.state.changed.v1 payload (event 019eb748).
        event = {
            "change_type": "new_evidence",
            "canonical_types": [
                "listed_on",
                "supplier_of",
                "supplier_of",
                "supplier_of",
                "supplier_of",
                "competes_with",
                "competes_with",
            ],
            "relation_ids": ["x"] * 7,
        }
        detail = _compose_graph_change_detail(event)
        assert detail == "graph update: 7 new links (4 supplier, 2 competitor, 1 listing)"

    def test_count_from_canonical_types_when_relation_ids_empty(self) -> None:
        # Live event 019eb7d5: relation_ids=[] but canonical_types=["produces"].
        event = {"change_type": "new_evidence", "canonical_types": ["produces"], "relation_ids": []}
        detail = _compose_graph_change_detail(event)
        assert detail == "graph update: 1 new link (1 product)"

    def test_no_detail_falls_back_to_phrase(self) -> None:
        event = {"change_type": "new_evidence", "canonical_types": [], "relation_ids": []}
        assert _compose_graph_change_detail(event) == "graph update"

    def test_unknown_change_type_uses_generic_phrase(self) -> None:
        event = {"change_type": "weird", "canonical_types": ["supplier_of"], "relation_ids": ["x"]}
        assert _compose_graph_change_detail(event) == "graph update: 1 new link (1 supplier)"


@pytest.mark.unit
class TestComposeAlertTitleWithGraphEvent:
    def test_graph_change_with_ticker_and_event(self) -> None:
        event = {
            "change_type": "new_evidence",
            "canonical_types": ["supplier_of", "supplier_of", "competes_with"],
            "relation_ids": ["a", "b", "c"],
        }
        title = _compose_alert_title(
            signal_label="MEDIUM signal",
            entity_name="Apple Inc.",
            ticker="AAPL",
            alert_type=AlertType.GRAPH_CHANGE,
            is_signal_label_fallback=True,
            event=event,
        )
        assert title == "AAPL — graph update: 3 new links (2 supplier, 1 competitor)"

    def test_graph_change_no_subject_capitalised_headline(self) -> None:
        event = {
            "change_type": "new_evidence",
            "canonical_types": ["supplier_of"],
            "relation_ids": ["a"],
        }
        title = _compose_alert_title(
            signal_label="MEDIUM signal",
            entity_name=None,
            ticker=None,
            alert_type=AlertType.GRAPH_CHANGE,
            is_signal_label_fallback=True,
            event=event,
        )
        # No subject → detail capitalised as a standalone headline.
        assert title == "Graph update: 1 new link (1 supplier)"
        assert title != "Graph pattern change"


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
        # Ticker-first subject ordering + em-dash separator (Wave-4 upgrade).
        assert alert.title == "AAPL — Bullish guidance"

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
