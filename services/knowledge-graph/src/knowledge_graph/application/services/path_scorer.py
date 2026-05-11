"""PathScorer — computes harmonic/diversity/surprise/composite scores (T-E1-03).

Pure application-layer service: no infrastructure imports.

Algorithm (PRD-0074 §9.3):
  harmonic_score  = harmonic_mean(edge_confs)          — zero confidence clamped to 1e-6
  diversity_score = 1 - (max_type_count / hop_count)   — rewards type variety
  surprise_score  = 1 - (signature_freq / total_paths) — rare signature = high surprise
  composite_score = min(h*0.4 + d*0.35 + s*0.25 + (0.1 if template_match else 0), 1.0)
                    rounded to 6 decimal places
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.domain.entities.path_insight import (
    PathEdge,
    PathInsight,
    PathNode,
)

if TYPE_CHECKING:
    from knowledge_graph.infrastructure.age.path_discovery import RawPath


def _harmonic_mean(values: tuple[float, ...]) -> float:
    """Compute the harmonic mean of ``values``, clamping zeros to 1e-6."""
    if not values:
        return 0.0
    clamped = tuple(max(v, 1e-6) for v in values)
    n = len(clamped)
    # harmonic mean = n / sum(1/v for v in values)
    return n / sum(1.0 / v for v in clamped)


def _diversity_score(node_types: tuple[str, ...], hop_count: int) -> float:
    """Reward paths that traverse diverse entity types.

    diversity_score = 1 - (max_type_count / hop_count)

    hop_count is the number of edges (= hops), NOT the number of nodes.
    We measure type variety across the *traversed* nodes — those reached by
    each hop — which means we exclude the anchor (start) node.  A path with
    N hops has N+1 nodes total; after dropping the anchor we have exactly N
    nodes, so max_type_count / hop_count is always in [1/N, 1] and the
    diversity score is always in [0, 1].

    BUG FIX (DP-PLAN-0074-01): the original code passed all node_types
    (including the anchor) making max_type_count potentially N+1 and
    producing a negative diversity score when all nodes share the same type.
    """
    if hop_count == 0:
        return 0.0
    # Exclude the anchor node (index 0); the remaining `hop_count` entries
    # correspond one-to-one to the hops, keeping the ratio in [0, 1].
    traversed_types = node_types[1:]
    counts = Counter(traversed_types)
    max_count = max(counts.values(), default=0)
    return max(0.0, 1.0 - (max_count / hop_count))


def _surprise_score(
    signature: tuple[str, ...],
    all_paths: list[RawPath],
) -> float:
    """Penalise common relation-type signatures.

    surprise_score = 1 - (signature_freq / total_paths)
    """
    total = len(all_paths)
    if total == 0:
        return 1.0
    freq = sum(1 for p in all_paths if p.rel_types == signature)
    return 1.0 - (freq / total)


def _composite(
    harmonic: float,
    diversity: float,
    surprise: float,
    template_match: str | None,
) -> float:
    """Compute the composite score, clamped to [0, 1] and rounded to 6dp."""
    raw = harmonic * 0.4 + diversity * 0.35 + surprise * 0.25 + (0.1 if template_match else 0.0)
    return round(min(raw, 1.0), 6)


class PathScorer:
    """Score a single RawPath relative to all candidate paths for an anchor.

    Usage::

        scorer = PathScorer()
        insights = [scorer.score(p, all_paths) for p in all_paths]

    Args:
    ----
        template_match: Pre-computed template name for the path (or None).
                        Callers should pass the result of PathTemplateMatcher.match().
    """

    def score(
        self,
        raw_path: RawPath,
        all_paths: list[RawPath],
        template_match: str | None = None,
    ) -> PathInsight:
        """Convert a RawPath to a fully-scored PathInsight.

        Args:
        ----
            raw_path:      The path to score.
            all_paths:     All candidate paths for the same anchor (used for
                           surprise score computation).
            template_match: Optional template name matched by PathTemplateMatcher.

        Returns:
        -------
            A frozen PathInsight with llm_explanation=None (Wave E2 deferred).
        """
        hop_count = raw_path.hop_count

        # Build domain value objects.
        nodes = tuple(
            PathNode(
                entity_id=_parse_uuid(nid),
                name=str(nn),
                entity_type=str(nt),
            )
            for nid, nn, nt in zip(
                raw_path.node_ids,
                raw_path.node_names,
                raw_path.node_types,
                strict=False,
            )
        )
        edges = tuple(
            PathEdge(
                relation_type=str(rt),
                confidence=float(conf),
            )
            for rt, conf in zip(raw_path.rel_types, raw_path.edge_confs, strict=False)
        )

        harmonic = _harmonic_mean(raw_path.edge_confs)
        diversity = _diversity_score(raw_path.node_types, hop_count)
        surprise = _surprise_score(raw_path.rel_types, all_paths)
        composite = _composite(harmonic, diversity, surprise, template_match)

        return PathInsight(
            insight_id=new_uuid7(),
            anchor_entity_id=_parse_uuid(raw_path.node_ids[0]) if raw_path.node_ids else new_uuid7(),
            hop_count=hop_count,
            path_nodes=nodes,
            path_edges=edges,
            harmonic_score=round(harmonic, 6),
            diversity_score=round(diversity, 6),
            surprise_score=round(surprise, 6),
            composite_score=composite,
            template_match=template_match,
            # ADR-0074-001: LLM explanation deferred to Wave E2.
            llm_explanation=None,
            explanation_model=None,
            computed_at=utc_now(),
        )


def _parse_uuid(value: object) -> UUID:
    """Parse a UUID from a string, returning a new UUID4 on failure."""
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return new_uuid7()
