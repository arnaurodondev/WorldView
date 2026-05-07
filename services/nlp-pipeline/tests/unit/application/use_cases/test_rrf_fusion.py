"""Unit tests for the pure RRF helper (PLAN-0063 W5-3 T-02).

The fusion function is purely functional — these tests assert numerical
correctness, ordering invariants, dedup behaviour, and the optional
weights argument (used by the W5-3 hybrid use case for the adaptive
lexical boost).
"""

from __future__ import annotations

import math

import pytest
from nlp_pipeline.application.use_cases._rrf import DEFAULT_K, reciprocal_rank_fuse


def test_rrf_single_list_preserves_order() -> None:
    """A single ranking → identical order in the output (no fusion to do)."""
    ranking = ["a", "b", "c", "d"]
    fused = reciprocal_rank_fuse([ranking])
    assert [item for item, _score in fused] == ranking


def test_rrf_dedups_items_in_both_lists() -> None:
    """An item present in two rankings appears once with summed contribution."""
    fused = reciprocal_rank_fuse([["a", "b"], ["a", "c"]])
    items = [item for item, _ in fused]
    assert items.count("a") == 1
    # All distinct items present.
    assert set(items) == {"a", "b", "c"}


def test_rrf_boosts_items_in_both_lists_above_one_only() -> None:
    """Item ranked top-3 in both rankings beats item only ranked rank-1 in one.

    This is the load-bearing property for hybrid retrieval — chunks that
    surface in BOTH the ANN and lexical legs should rank above chunks only
    found by one leg.
    """
    in_both = "shared"
    only_one = "only_lex"
    fused = reciprocal_rank_fuse(
        [
            [in_both, "a", "b"],  # rank 0 (ann)
            [only_one, in_both, "c"],  # rank 1 (lex)
        ]
    )
    items = [item for item, _ in fused]
    # `shared` is rank-0 in list1 + rank-1 in list2 → 1/61 + 1/62
    # `only_lex` is rank-0 in list2 only → 1/61
    # So shared > only_lex.
    assert items.index(in_both) < items.index(only_one)


def test_rrf_with_disjoint_lists_returns_all() -> None:
    """No overlap → all items present with their per-list contribution only."""
    fused = reciprocal_rank_fuse([["a", "b"], ["c", "d"]])
    assert {item for item, _ in fused} == {"a", "b", "c", "d"}


def test_rrf_k_parameter_controls_decay() -> None:
    """A smaller k → steeper decay between rank 0 and rank 1.

    We assert numerically: with k=10 the rank-0/rank-1 gap is wider than
    with k=100 for the same single-list input.
    """
    fused_small = reciprocal_rank_fuse([["a", "b"]], k=10)
    fused_large = reciprocal_rank_fuse([["a", "b"]], k=100)
    score_a_small = fused_small[0][1]
    score_b_small = fused_small[1][1]
    score_a_large = fused_large[0][1]
    score_b_large = fused_large[1][1]
    gap_small = score_a_small - score_b_small
    gap_large = score_a_large - score_b_large
    assert gap_small > gap_large


def test_rrf_keeps_first_list_representative() -> None:
    """When an item appears in multiple lists we keep the first list's copy.

    The hybrid use case relies on this so the `EnrichedChunkResult` returned
    is the ANN-leg version (which has the correct vector score recorded),
    not the lexical-leg version (whose `score` is a ts_rank).
    """

    class FakeRow:
        """Minimal placeholder; equality on `chunk_id`, identity preserved otherwise."""

        def __init__(self, chunk_id: str, leg: str) -> None:
            self.chunk_id = chunk_id
            self.leg = leg

        def __eq__(self, other: object) -> bool:
            return isinstance(other, FakeRow) and self.chunk_id == other.chunk_id

        def __hash__(self) -> int:
            return hash(self.chunk_id)

    ann_copy = FakeRow("c-1", leg="ann")
    lex_copy = FakeRow("c-1", leg="lex")
    fused = reciprocal_rank_fuse(
        [[ann_copy], [lex_copy]],
        key=lambda r: r.chunk_id,
    )
    assert len(fused) == 1
    assert fused[0][0].leg == "ann"


def test_rrf_empty_inputs_return_empty() -> None:
    """All-empty rankings → empty output, no exception."""
    assert reciprocal_rank_fuse([]) == []
    assert reciprocal_rank_fuse([[], []]) == []


def test_rrf_with_weights_doubles_lex_contribution() -> None:
    """weights=(1.0, 2.0): a lex-only top-1 hit scores 2 * 1/(60+1) = 2/61."""
    fused = reciprocal_rank_fuse([[], ["item"]], weights=(1.0, 2.0))
    assert len(fused) == 1
    item, score = fused[0]
    assert item == "item"
    assert math.isclose(score, 2.0 / (DEFAULT_K + 1))


def test_rrf_weights_length_mismatch_raises() -> None:
    """Defensive: weights length must match rankings length."""
    with pytest.raises(ValueError):
        reciprocal_rank_fuse([["a"], ["b"]], weights=(1.0,))
