"""Tests for compute_display_relevance_score (PLAN-0055 C-3).

Pinned formula: 0.5*market + 0.4*llm + 0.1*routing when LLM is present;
renormalized (5/6, 1/6) on the remaining two when LLM is None.
"""

from __future__ import annotations

import pytest
from nlp_pipeline.application.services.relevance_score import compute_display_relevance_score

pytestmark = pytest.mark.unit


class TestComputeDisplayRelevanceScore:
    def test_with_llm_uses_full_formula(self) -> None:
        # 0.5*0.4 + 0.4*0.8 + 0.1*0.6 = 0.20 + 0.32 + 0.06 = 0.58
        result = compute_display_relevance_score(
            market_score=0.4,
            routing_score=0.6,
            llm_score=0.8,
        )
        assert result == pytest.approx(0.58, abs=1e-6)

    def test_without_llm_renormalizes(self) -> None:
        # (0.5/0.6) * 0.4 + (0.1/0.6) * 0.6 = 0.3333... + 0.10 = 0.4333...
        result = compute_display_relevance_score(
            market_score=0.4,
            routing_score=0.6,
            llm_score=None,
        )
        assert result == pytest.approx(5 / 6 * 0.4 + 1 / 6 * 0.6, abs=1e-6)

    def test_renormalized_weights_sum_to_one(self) -> None:
        # Pinning: when llm is None, all-1.0 inputs must yield 1.0.
        result = compute_display_relevance_score(
            market_score=1.0,
            routing_score=1.0,
            llm_score=None,
        )
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_zero_llm_is_distinct_from_missing_llm(self) -> None:
        # llm=0.0 → still pulls the display down via the 0.4 weight.
        # llm=None → renormalizes; market & routing carry full weight.
        with_zero = compute_display_relevance_score(market_score=1.0, routing_score=1.0, llm_score=0.0)
        without_llm = compute_display_relevance_score(market_score=1.0, routing_score=1.0, llm_score=None)
        # 0.5*1 + 0.4*0 + 0.1*1 = 0.6  vs  fully renormalized 1.0
        assert with_zero == pytest.approx(0.6, abs=1e-6)
        assert without_llm == pytest.approx(1.0, abs=1e-6)
        assert with_zero < without_llm

    def test_clamps_to_unit_interval(self) -> None:
        # Even malformed upstream signals must produce a [0,1] output.
        out_high = compute_display_relevance_score(market_score=2.0, routing_score=2.0, llm_score=2.0)
        out_low = compute_display_relevance_score(market_score=-1.0, routing_score=-1.0, llm_score=-1.0)
        assert 0.0 <= out_high <= 1.0
        assert 0.0 <= out_low <= 1.0
