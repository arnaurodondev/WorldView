"""Unit tests for the 4-step confidence formula (PRD §10.1)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from knowledge_graph.domain.confidence import (
    _TEMPORAL_CLAIM_ALPHA,
    ContradictionInput,
    EvidenceInput,
    compute_confidence,
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
    def test_temporal_claim_uses_fixed_alpha(self) -> None:
        """TEMPORAL_CLAIM uses 0.02310 regardless of decay_alpha parameter.

        Two evidence pieces: fresh high-weight + very old low-weight.
        With alpha=0 (RELATION_STATE): equally weighted → average = 0.5.
        With alpha=0.02310 (TEMPORAL_CLAIM): old piece nearly zeroed → ~0.9.
        """
        fresh = _evidence(source_weight=0.9, source_type="A", source_name="srcA", days_ago=0)
        old = _evidence(source_weight=0.1, source_type="B", source_name="srcB", days_ago=365)

        result_rs = compute_confidence(
            evidence=[fresh, old],
            contradictions=[],
            decay_alpha=0.0,  # no decay for RELATION_STATE
            semantic_mode=SemanticMode.RELATION_STATE,
            now=_NOW,
        )
        result_tc = compute_confidence(
            evidence=[fresh, old],
            contradictions=[],
            decay_alpha=0.0,  # ignored by TEMPORAL_CLAIM; uses 0.02310
            semantic_mode=SemanticMode.TEMPORAL_CLAIM,
            now=_NOW,
        )
        # TEMPORAL_CLAIM down-weights old evidence → support closer to 0.9
        # RELATION_STATE with alpha=0 treats both equally → support = 0.5
        assert result_tc.support > result_rs.support

    def test_temporal_claim_alpha_is_30_day_half_life(self) -> None:
        """exp(-0.02310 * 30) ≈ 0.5 (30-day half-life)."""
        expected_half = math.exp(-_TEMPORAL_CLAIM_ALPHA * 30)
        assert abs(expected_half - 0.5) < 0.01


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
