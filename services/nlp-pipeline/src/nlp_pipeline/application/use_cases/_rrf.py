"""Reciprocal Rank Fusion — pure functional helper (PLAN-0063 W5-3).

Implements the classical RRF combiner from Cormack, Clarke, Buettcher (SIGIR
2009): score(item) = Σ_i  w_i / (k + rank_i(item)).  When weights are all 1
this reduces to the standard formulation; non-uniform weights let the caller
boost a specific ranking — the W5-3 hybrid use case uses this to tilt the
fusion toward the lexical leg when the query contains rare identifier tokens
(per L9, the boost factor is tunable via Settings.hybrid_lexical_boost).

Purity contract
---------------
This module MUST stay free of:
  * I/O — no DB, no HTTP, no Valkey
  * structlog / observability — no side-effecting logger calls
  * DI containers / settings — every input is an explicit argument

That keeps the fusion function trivially unit-testable (no mocks needed) and
re-usable from any service layer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

# Default RRF damping constant. The 60 came from the original SIGIR paper —
# small enough that the top of one ranking still dominates the bottom of
# another, large enough to dampen rank-1 single-list winners.
DEFAULT_K: int = 60

T = TypeVar("T")


def reciprocal_rank_fuse(
    rankings: Sequence[Sequence[T]],
    *,
    k: int = DEFAULT_K,
    key: Callable[[T], Any] = lambda x: x,
    weights: Sequence[float] | None = None,
) -> list[tuple[T, float]]:
    """Fuse multiple ranked lists into a single ranked list via RRF.

    Args:
        rankings: One sequence of items per ranking. The position within
            each inner sequence is the (0-indexed) rank — the first element
            is rank 0.
        k: RRF damping constant (higher → flatter score curve).
        key: Function returning the dedup identity of an item. Two items
            with the same key are considered the same item across rankings.
            Defaults to identity (works when items are hashable + Eq-stable
            like UUIDs or strings).
        weights: Optional per-ranking weight. When ``None``, every ranking
            contributes uniformly with weight 1.0. When provided, must have
            the same length as `rankings` — element i scales the contribution
            of the i-th ranking. The W5-3 hybrid use case supplies
            ``(1.0, lexical_boost)`` to tilt fusion toward FTS for queries
            with rare identifier tokens.

    Returns:
        A list of ``(item, fused_score)`` tuples sorted by score descending.
        For items appearing in multiple rankings, the *first* ranking's copy
        is preserved in the output (so e.g. EnrichedChunkResult metadata from
        the ANN leg wins over the lexical leg when both produce the same chunk).

    Raises:
        ValueError: when len(weights) != len(rankings).
    """
    if weights is not None and len(weights) != len(rankings):
        raise ValueError(f"weights length {len(weights)} != rankings length {len(rankings)}")

    # Score table keyed by the dedup identity. We separately remember the
    # first-seen item for each key so the caller's representative survives
    # the fusion.
    scores: dict[Any, float] = {}
    representatives: dict[Any, T] = {}

    for ranking_idx, ranking in enumerate(rankings):
        weight = 1.0 if weights is None else float(weights[ranking_idx])
        for rank, item in enumerate(ranking):
            ident = key(item)
            # 1-indexed rank in the formula: rank=0 (top of the list) →
            # contribution = w / (k + 1).
            contribution = weight / (k + rank + 1)
            if ident in scores:
                scores[ident] += contribution
            else:
                scores[ident] = contribution
                representatives[ident] = item

    # Sort by score DESC; for ties we fall back to insertion order via the
    # representative dict (Python 3.7+ guarantees insertion order on dicts).
    fused: list[tuple[T, float]] = [
        (representatives[ident], score)
        for ident, score in sorted(
            scores.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
    ]
    return fused
