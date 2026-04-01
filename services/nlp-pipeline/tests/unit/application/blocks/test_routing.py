"""Unit tests for Block 5 — Routing Score (T-C-2-05)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from nlp_pipeline.application.blocks.routing import (
    SIGNAL_WEIGHTS,
    TIER_DEEP,
    TIER_LIGHT,
    TIER_MEDIUM,
    _assign_tier,
    _entity_density_signal,
    _extraction_yield_signal,
    _recency_signal,
    _watchlist_signal,
    compute_routing_score,
)
from nlp_pipeline.domain.enums import MentionClass, RoutingTier
from nlp_pipeline.domain.models import EntityMention


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _mention(cls: MentionClass, entity_id: uuid.UUID | None = None) -> EntityMention:
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text="test",
        mention_class=cls,
        confidence=0.90,
        char_start=0,
        char_end=4,
        resolved_entity_id=entity_id,
    )


@pytest.mark.unit
class TestSignalWeights:
    def test_weights_sum_to_1(self) -> None:
        """Critical: module-level assertion — weights must sum to exactly 1.0."""
        total = sum(SIGNAL_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_seven_signals(self) -> None:
        assert len(SIGNAL_WEIGHTS) == 7

    def test_all_positive(self) -> None:
        assert all(v > 0 for v in SIGNAL_WEIGHTS.values())


@pytest.mark.unit
class TestTierAssignment:
    def test_deep_at_threshold(self) -> None:
        assert _assign_tier(TIER_DEEP) == RoutingTier.DEEP

    def test_deep_above_threshold(self) -> None:
        assert _assign_tier(1.0) == RoutingTier.DEEP

    def test_medium_at_threshold(self) -> None:
        assert _assign_tier(TIER_MEDIUM) == RoutingTier.MEDIUM

    def test_medium_just_below_deep(self) -> None:
        assert _assign_tier(TIER_DEEP - 0.001) == RoutingTier.MEDIUM

    def test_light_at_threshold(self) -> None:
        assert _assign_tier(TIER_LIGHT) == RoutingTier.LIGHT

    def test_light_just_below_medium(self) -> None:
        assert _assign_tier(TIER_MEDIUM - 0.001) == RoutingTier.LIGHT

    def test_suppress_below_light(self) -> None:
        assert _assign_tier(TIER_LIGHT - 0.001) == RoutingTier.SUPPRESS

    def test_suppress_at_zero(self) -> None:
        assert _assign_tier(0.0) == RoutingTier.SUPPRESS

    def test_edge_at_045(self) -> None:
        """Edge case: exactly 0.45 should be MEDIUM, not LIGHT."""
        assert _assign_tier(0.45) == RoutingTier.MEDIUM

    def test_edge_at_020(self) -> None:
        """Edge case: exactly 0.20 should be LIGHT, not SUPPRESS."""
        assert _assign_tier(0.20) == RoutingTier.LIGHT

    def test_edge_at_070(self) -> None:
        """Edge case: exactly 0.70 should be DEEP, not MEDIUM."""
        assert _assign_tier(0.70) == RoutingTier.DEEP


@pytest.mark.unit
class TestEntityDensitySignal:
    def test_empty_mentions(self) -> None:
        assert _entity_density_signal([]) == 0.0

    def test_only_counts_org_and_fi(self) -> None:
        mentions = [
            _mention(MentionClass.ORGANIZATION),
            _mention(MentionClass.FINANCIAL_INSTITUTION),
            _mention(MentionClass.PERSON),  # not counted
            _mention(MentionClass.LOCATION),  # not counted
        ]
        # 2 org+fi / 15 = 0.133
        result = _entity_density_signal(mentions)
        assert abs(result - 2 / 15) < 1e-9

    def test_capped_at_1(self) -> None:
        # 15+ org mentions should cap at 1.0
        mentions = [_mention(MentionClass.ORGANIZATION) for _ in range(20)]
        assert _entity_density_signal(mentions) == 1.0


@pytest.mark.unit
class TestRecencySignal:
    def test_recent_article_high_signal(self) -> None:
        published_at = _now() - timedelta(hours=1)
        result = _recency_signal(published_at, _now())
        assert result > 0.95  # almost fresh

    def test_old_article_low_signal(self) -> None:
        published_at = _now() - timedelta(hours=200)
        result = _recency_signal(published_at, _now())
        assert result < 0.02  # very old

    def test_none_published_uses_extracted_at(self) -> None:
        extracted_at = _now() - timedelta(hours=2)
        result = _recency_signal(None, extracted_at)
        assert 0.85 < result < 1.0

    def test_future_date_clamps_to_one(self) -> None:
        # published_at in the future (clock skew) — hours are negative → clamped to 0
        published_at = _now() + timedelta(hours=1)
        result = _recency_signal(published_at, _now())
        assert result == 1.0  # exp(-0.02 * 0) = 1.0


@pytest.mark.unit
class TestWatchlistSignal:
    def test_empty_watched_set_returns_zero(self) -> None:
        mentions = [_mention(MentionClass.ORGANIZATION, uuid.uuid4())]
        result = _watchlist_signal(mentions, frozenset())
        assert result == 0.0

    def test_one_overlap_out_of_3(self) -> None:
        entity_id = uuid.uuid4()
        mentions = [_mention(MentionClass.ORGANIZATION, entity_id)]
        result = _watchlist_signal(mentions, frozenset([entity_id]))
        assert abs(result - 1 / 3) < 1e-9

    def test_three_or_more_overlaps_caps_at_1(self) -> None:
        ids = [uuid.uuid4() for _ in range(5)]
        mentions = [_mention(MentionClass.ORGANIZATION, eid) for eid in ids]
        result = _watchlist_signal(mentions, frozenset(ids))
        assert result == 1.0

    def test_unresolved_mentions_not_counted(self) -> None:
        """Mentions without resolved_entity_id don't count even if watched."""
        mentions = [
            EntityMention(
                mention_id=uuid.uuid4(),
                doc_id=uuid.uuid4(),
                section_id=uuid.uuid4(),
                mention_text="Tesla",
                mention_class=MentionClass.ORGANIZATION,
                confidence=0.90,
                char_start=0,
                char_end=5,
                resolved_entity_id=None,  # unresolved
            )
        ]
        watched = frozenset([uuid.uuid4()])  # some watched entity
        assert _watchlist_signal(mentions, watched) == 0.0


@pytest.mark.unit
class TestExtractionYieldSignal:
    def test_zero_zeros(self) -> None:
        assert _extraction_yield_signal(0, 0) == 0.0

    def test_caps_at_1(self) -> None:
        result = _extraction_yield_signal(100, 100)
        assert result == 1.0

    def test_formula(self) -> None:
        # 10 mentions, 4 sections → 0.6*(10/20) + 0.4*(4/8) = 0.3 + 0.2 = 0.5
        result = _extraction_yield_signal(10, 4)
        assert abs(result - 0.5) < 1e-9


@pytest.mark.unit
class TestComputeRoutingScore:
    def test_deep_tier_high_signal(self) -> None:
        doc_id = uuid.uuid4()
        decision_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        mentions = [_mention(MentionClass.ORGANIZATION, entity_id) for _ in range(10)]

        decision = compute_routing_score(
            doc_id=doc_id,
            decision_id=decision_id,
            source_type="sec_8k",
            published_at=_now() - timedelta(hours=1),
            extracted_at=_now(),
            mentions=mentions,
            section_count=6,
            source_trust_weight=0.92,
            novelty_score=0.90,
            watched_entity_ids=frozenset([entity_id]),
        )
        assert decision.routing_tier == RoutingTier.DEEP
        assert len(decision.feature_scores) == 7

    def test_suppress_tier_low_signal(self) -> None:
        decision = compute_routing_score(
            doc_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            source_type="manual",
            published_at=_now() - timedelta(hours=500),  # very old
            extracted_at=_now(),
            mentions=[],  # no mentions
            section_count=0,
            source_trust_weight=0.50,
            novelty_score=0.0,
            watched_entity_ids=frozenset(),
        )
        assert decision.routing_tier == RoutingTier.SUPPRESS

    def test_feature_scores_dict_has_7_keys(self) -> None:
        decision = compute_routing_score(
            doc_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            source_type="eodhd_news",
            published_at=None,
            extracted_at=_now(),
            mentions=[],
            section_count=3,
            source_trust_weight=0.60,
            novelty_score=0.50,
            watched_entity_ids=frozenset(),
        )
        assert len(decision.feature_scores) == 7

    def test_composite_score_clamped_to_0_1(self) -> None:
        decision = compute_routing_score(
            doc_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            source_type="sec_8k",
            published_at=_now(),
            extracted_at=_now(),
            mentions=[_mention(MentionClass.ORGANIZATION) for _ in range(20)],
            section_count=20,
            source_trust_weight=1.0,
            novelty_score=1.0,
            watched_entity_ids=frozenset(),
        )
        assert 0.0 <= decision.composite_score <= 1.0
