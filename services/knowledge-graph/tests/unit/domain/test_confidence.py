"""Unit tests for the 4-step confidence formula (PRD §10.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from knowledge_graph.domain.confidence import (
    ContradictionInput,
    EvidenceInput,
    compute_confidence,
    compute_confidence_beta,
)
from knowledge_graph.domain.enums import SemanticMode

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC)


def _evidence(
    *,
    source_weight: float = 0.8,
    source_type: str = "sec_10k",
    source_name: str = "Apple Inc.",
    days_ago: float = 0.0,
) -> EvidenceInput:
    return EvidenceInput(
        source_weight=source_weight,
        source_type=source_type,
        source_name=source_name,
        evidence_date=_NOW - timedelta(days=days_ago),
    )


def _contradiction(*, strength: float = 0.5, days_ago: float = 0.0) -> ContradictionInput:
    return ContradictionInput(
        strength=strength,
        detected_at=_NOW - timedelta(days=days_ago),
    )


class TestEmptyInputs:
    def test_no_evidence_returns_zero(self) -> None:
        result = compute_confidence(
            evidence=[],
            contradictions=[],
            decay_alpha=0.001,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.final == 0.0
        assert result.support == 0.0
        assert result.corroboration == 0.0
        assert result.contradiction == 0.0


class TestSupport:
    def test_single_evidence_support_equals_source_weight(self) -> None:
        ev = _evidence(source_weight=0.9, days_ago=0)
        result = compute_confidence(
            evidence=[ev],
            contradictions=[],
            decay_alpha=0.0,  # no decay
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert abs(result.support - 0.9) < 1e-6

    def test_support_weighted_average_not_count(self) -> None:
        """Normalize by sum(temporal_weight), NOT count of evidence."""
        # Two evidence pieces, one very stale (tiny weight), one fresh
        fresh = _evidence(source_weight=0.9, days_ago=0)
        stale = _evidence(source_weight=0.1, days_ago=1000)  # almost zero weight with alpha=0.01
        alpha = 0.01
        result = compute_confidence(
            evidence=[fresh, stale],
            contradictions=[],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        # Stale evidence has negligible weight; support ≈ 0.9 (not (0.9+0.1)/2 = 0.5)
        assert result.support > 0.7, f"Expected support > 0.7, got {result.support}"

    def test_multiple_same_source_average(self) -> None:
        evs = [_evidence(source_weight=0.8, days_ago=0) for _ in range(5)]
        result = compute_confidence(
            evidence=evs,
            contradictions=[],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert abs(result.support - 0.8) < 1e-6


class TestCorroboration:
    def test_single_source_no_corroboration(self) -> None:
        evs = [_evidence(source_type="sec_10k", source_name="AAPL", days_ago=0) for _ in range(3)]
        result = compute_confidence(
            evidence=evs,
            contradictions=[],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        # All same (type, name) → only 1 distinct source → gain = 1 * 0.05 = 0.05
        assert abs(result.corroboration - 0.05) < 1e-6

    def test_four_distinct_sources_hits_cap(self) -> None:
        evs = [
            _evidence(source_type="sec_10k", source_name="AAPL"),
            _evidence(source_type="sec_10q", source_name="AAPL"),
            _evidence(source_type="press_release", source_name="AAPL"),
            _evidence(source_type="analyst_report", source_name="Barclays"),
        ]
        result = compute_confidence(
            evidence=evs,
            contradictions=[],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        # 4 distinct sources x 0.05 = 0.20 = cap
        assert abs(result.corroboration - 0.20) < 1e-6

    def test_stale_source_excluded_from_corroboration(self) -> None:
        """Evidence with temporal_weight < 0.1 should NOT count for corroboration."""
        alpha = 0.05
        # At alpha=0.05, exp(-0.05 * 60) ≈ 0.05 < 0.1 — stale
        stale = _evidence(source_type="sec_10k", source_name="SRC_A", days_ago=60)
        fresh = _evidence(source_type="sec_10q", source_name="SRC_B", days_ago=0)
        result = compute_confidence(
            evidence=[stale, fresh],
            contradictions=[],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        # Only the fresh source qualifies: 1 x 0.05 = 0.05
        assert abs(result.corroboration - 0.05) < 1e-6

    def test_corroboration_capped_at_0_20(self) -> None:
        # 10 distinct sources would give 0.5 uncapped
        evs = [_evidence(source_type=f"type_{i}", source_name=f"name_{i}", days_ago=0) for i in range(10)]
        result = compute_confidence(
            evidence=evs,
            contradictions=[],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.corroboration <= 0.20 + 1e-9


class TestContradiction:
    def test_no_contradictions_penalty_zero(self) -> None:
        result = compute_confidence(
            evidence=[_evidence()],
            contradictions=[],
            decay_alpha=0.001,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.contradiction == 0.0

    def test_single_contradiction(self) -> None:
        c = _contradiction(strength=0.5, days_ago=0)
        result = compute_confidence(
            evidence=[_evidence()],
            contradictions=[c],
            decay_alpha=0.0,  # no decay
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert abs(result.contradiction - 0.5) < 1e-6

    def test_top_three_used(self) -> None:
        """Only top-3 decayed strengths contribute — 4th and beyond are ignored."""
        contras = [_contradiction(strength=s, days_ago=0) for s in [0.4, 0.3, 0.2, 0.1]]
        result = compute_confidence(
            evidence=[_evidence()],
            contradictions=contras,
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        # Top-3: 0.4 + 0.3 + 0.2 = 0.9 → capped at 0.60
        assert abs(result.contradiction - 0.60) < 1e-6

    def test_contradiction_capped_at_0_60(self) -> None:
        contras = [_contradiction(strength=1.0, days_ago=0) for _ in range(5)]
        result = compute_confidence(
            evidence=[_evidence()],
            contradictions=contras,
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.contradiction <= 0.60 + 1e-9

    def test_contradiction_decays_over_time(self) -> None:
        alpha = 0.02310
        # Fresh vs 30-days-old: exp(-0.02310*30) ≈ 0.5
        fresh = _contradiction(strength=0.5, days_ago=0)
        old = _contradiction(strength=0.5, days_ago=30)
        result_fresh = compute_confidence(
            evidence=[_evidence()],
            contradictions=[fresh],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        result_old = compute_confidence(
            evidence=[_evidence()],
            contradictions=[old],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result_fresh.contradiction > result_old.contradiction


class TestSemanticModeDecay:
    def test_temporal_claim_uses_relation_decay_alpha(self) -> None:
        """TEMPORAL_CLAIM uses relation decay_alpha (same as RELATION_STATE)."""
        fresh = _evidence(source_weight=0.9, source_type="A", source_name="srcA", days_ago=0)
        old = _evidence(source_weight=0.1, source_type="B", source_name="srcB", days_ago=365)
        alpha = 0.011552  # MEDIUM half-life (60 days)

        result_rs = compute_confidence(
            evidence=[fresh, old],
            contradictions=[],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        result_tc = compute_confidence(
            evidence=[fresh, old],
            contradictions=[],
            decay_alpha=alpha,
            semantic_mode=SemanticMode.TEMPORAL_CLAIM,
            now=_NOW,
        )
        assert result_tc.support == pytest.approx(result_rs.support)
        assert result_tc.corroboration == pytest.approx(result_rs.corroboration)


class TestFinalBounded:
    def test_final_never_below_zero(self) -> None:
        """Massive contradiction should not push final below 0."""
        contras = [_contradiction(strength=1.0) for _ in range(10)]
        result = compute_confidence(
            evidence=[_evidence(source_weight=0.1)],
            contradictions=contras,
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.final >= 0.0

    def test_final_never_above_one(self) -> None:
        evs = [_evidence(source_weight=1.0) for _ in range(5)]
        result = compute_confidence(
            evidence=evs,
            contradictions=[],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        assert result.final <= 1.0

    def test_validate_passes_after_compute(self) -> None:
        """ConfidenceComponents produced by compute_confidence always passes validate()."""
        evs = [
            _evidence(source_type="sec_10k", source_name="AAPL", source_weight=0.95, days_ago=1),
            _evidence(source_type="analyst_report", source_name="Barclays", source_weight=0.80, days_ago=5),
        ]
        contras = [_contradiction(strength=0.4, days_ago=10)]
        result = compute_confidence(
            evidence=evs,
            contradictions=contras,
            decay_alpha=0.003851,
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        result.validate()  # must not raise


# ===========================================================================
# PLAN-0109 W1 — Beta / subjective-logic backbone (compute_confidence_beta)
# ===========================================================================


class TestBetaBackbone:
    """The v2 Beta/subjective-logic confidence formula."""

    def test_no_evidence_stateful_returns_predicate_prior(self) -> None:
        """A stateful fact with no evidence sits at its predicate prior, u=1."""
        r = compute_confidence_beta(
            [],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.70,
            now=_NOW,
        )
        assert r.final == pytest.approx(0.70, abs=1e-9)
        assert r.uncertainty == pytest.approx(1.0, abs=1e-9)

    def test_no_evidence_signal_returns_low_floor(self) -> None:
        """A signal fact with no evidence floors low (not the extraction prior)."""
        r = compute_confidence_beta(
            [],
            [],
            decay_alpha=0.23105,
            semantic_mode=SemanticMode.TEMPORAL_CLAIM,
            base_confidence=0.45,
            now=_NOW,
            signal_decay_floor=0.1,
        )
        assert r.final == pytest.approx(0.1, abs=1e-9)

    def test_stateful_holds_regardless_of_age(self) -> None:
        """Stateful evidence does NOT decay — same confidence fresh or old."""
        fresh = compute_confidence_beta(
            [_evidence(source_weight=0.9, days_ago=0)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.7,
            now=_NOW,
        )
        old = compute_confidence_beta(
            [_evidence(source_weight=0.9, days_ago=2000)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.7,
            now=_NOW,
        )
        assert fresh.final == pytest.approx(old.final, abs=1e-9)

    def test_signal_decays_toward_floor_with_age(self) -> None:
        """An aged signal relaxes toward the low floor; a fresh one is higher."""
        fresh = compute_confidence_beta(
            [_evidence(source_weight=0.9, days_ago=0)],
            [],
            decay_alpha=0.23105,
            semantic_mode=SemanticMode.TEMPORAL_CLAIM,
            base_confidence=0.45,
            now=_NOW,
            signal_decay_floor=0.1,
        )
        old = compute_confidence_beta(
            [_evidence(source_weight=0.9, days_ago=60)],
            [],
            decay_alpha=0.23105,
            semantic_mode=SemanticMode.TEMPORAL_CLAIM,
            base_confidence=0.45,
            now=_NOW,
            signal_decay_floor=0.1,
        )
        assert old.final < fresh.final
        assert old.final == pytest.approx(0.1, abs=0.02)

    def test_more_independent_sources_raise_confidence_and_shrink_uncertainty(self) -> None:
        """Diminishing-returns corroboration: more sources → higher final, lower u."""
        one = compute_confidence_beta(
            [_evidence(source_type="sec_10k", source_name="A", source_weight=0.9)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        three = compute_confidence_beta(
            [
                _evidence(source_type="sec_10k", source_name="A", source_weight=0.9),
                _evidence(source_type="analyst_report", source_name="B", source_weight=0.9),
                _evidence(source_type="press_release", source_name="C", source_weight=0.9),
            ],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        assert three.final > one.final
        assert three.uncertainty < one.uncertainty

    def test_higher_source_trust_raises_confidence(self) -> None:
        """Graded source trust matters: a high-trust source beats a low-trust one."""
        high = compute_confidence_beta(
            [_evidence(source_weight=0.95)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        low = compute_confidence_beta(
            [_evidence(source_weight=0.55)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        assert high.final > low.final

    def test_contradiction_pulls_confidence_down(self) -> None:
        """Contradiction mass lowers the posterior mean."""
        no_contra = compute_confidence_beta(
            [_evidence(source_weight=0.9)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.6,
            now=_NOW,
        )
        with_contra = compute_confidence_beta(
            [_evidence(source_weight=0.9)],
            [_contradiction(strength=0.8, days_ago=0)],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.6,
            now=_NOW,
        )
        assert with_contra.final < no_contra.final

    def test_final_always_in_unit_interval(self) -> None:
        """Output is bounded by construction for extreme inputs."""
        r = compute_confidence_beta(
            [_evidence(source_weight=1.0) for _ in range(50)],
            [_contradiction(strength=1.0) for _ in range(50)],
            decay_alpha=0.0,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        assert 0.0 <= r.final <= 1.0
        assert 0.0 <= r.uncertainty <= 1.0

    def test_stateful_holds_while_valid(self) -> None:
        """A stateful fact with valid_to in the future holds (step not yet fired)."""
        r = compute_confidence_beta(
            [_evidence(source_weight=0.9)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.8,
            now=_NOW,
            valid_to=_NOW + timedelta(days=365),
        )
        assert r.final > 0.8  # evidence-backed, above prior

    def test_stateful_expired_drops_to_floor(self) -> None:
        """Once now > valid_to a stateful fact expires and drops to the low floor."""
        valid = compute_confidence_beta(
            [_evidence(source_weight=0.9)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.8,
            now=_NOW,
            valid_to=_NOW + timedelta(days=365),
            signal_decay_floor=0.1,
        )
        expired = compute_confidence_beta(
            [_evidence(source_weight=0.9)],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.8,
            now=_NOW,
            valid_to=_NOW - timedelta(days=1),
            signal_decay_floor=0.1,
        )
        assert expired.final < valid.final
        assert expired.final == pytest.approx(0.1, abs=1e-9)

    def test_syndicated_reprints_count_once(self) -> None:
        """3 reprints of the same story (shared dedup_key) < 3 independent sources."""
        syndicated = compute_confidence_beta(
            [
                EvidenceInput(0.9, "eodhd_news", "A", _NOW, dedup_key="wire1"),
                EvidenceInput(0.9, "finnhub_news", "B", _NOW, dedup_key="wire1"),
                EvidenceInput(0.9, "newsapi_news", "C", _NOW, dedup_key="wire1"),
            ],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        independent = compute_confidence_beta(
            [
                EvidenceInput(0.9, "eodhd_news", "A", _NOW, dedup_key="wireA"),
                EvidenceInput(0.9, "finnhub_news", "B", _NOW, dedup_key="wireB"),
                EvidenceInput(0.9, "newsapi_news", "C", _NOW, dedup_key="wireC"),
            ],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        assert syndicated.final < independent.final
        # The syndicated cluster contributes one source's mass, not three.
        assert syndicated.support_mass == pytest.approx(0.9, abs=1e-9)
        assert independent.support_mass == pytest.approx(2.7, abs=1e-9)

    def test_dedup_cluster_uses_best_member(self) -> None:
        """A syndication cluster contributes its highest-trust (best) member's mass."""
        r = compute_confidence_beta(
            [
                EvidenceInput(0.55, "newsapi_news", "low", _NOW, dedup_key="w"),
                EvidenceInput(0.95, "sec_10k", "high", _NOW, dedup_key="w"),
            ],
            [],
            decay_alpha=0.00095,
            semantic_mode=SemanticMode.RELATION_STATE,
            base_confidence=0.5,
            now=_NOW,
        )
        assert r.support_mass == pytest.approx(0.95, abs=1e-9)
