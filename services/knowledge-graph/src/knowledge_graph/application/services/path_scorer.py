"""PathScorer — computes harmonic/diversity/surprise/composite scores (T-E1-03).

Pure application-layer service: no infrastructure imports.

Algorithm (PRD-0074 §9.3):
  harmonic_score  = harmonic_mean(edge_confs)          — zero confidence clamped to 1e-6
  diversity_score = 1 - (max_type_count / hop_count)   — rewards type variety
  surprise_score  = 1 - (signature_freq / total_paths) — rare signature = high surprise
  hub_penalty     = log(max(edge_count, 2)) / log(max_degree)
                    applied per path: penalised = composite / (1 + max_hub_penalty_along_path)
  composite_score = min(h*0.4 + d*0.35 + s*0.25 + (0.1 if template_match else 0), 1.0)
                    then divided by (1 + hub_penalty), rounded to 6 decimal places

Hub penalty rationale (2026-05-23):
  When a generic hub entity (e.g. "Artificial Intelligence", 127+ edges) sits in the
  middle of many paths it inflates all scores equally, collapsing ranking diversity.
  The hub penalty scales down composite_score proportional to log(degree) so
  company-to-company paths remain unpenalised while AI-hub paths are down-weighted.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.graph_path_engine import edge_forward_at as _forward_at
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


def _build_node_degree_map(all_paths: list[RawPath]) -> dict[str, int]:
    """Count how many distinct paths each intermediate node appears in.

    The anchor node (index 0) is excluded — we only penalise intermediate hubs.
    This approximates the AGE graph degree without an extra DB round-trip.

    Returns a dict mapping node_id → path-occurrence-count.
    """
    counts: Counter[str] = Counter()
    for path in all_paths:
        # Skip index 0 (anchor) and the last node (endpoint).
        # Intermediate hubs are indices 1 .. len-2 for hop>=2.
        intermediates = path.node_ids[1:-1]
        # Use a set so repeated visits in the same path count only once.
        counts.update(set(intermediates))
    return dict(counts)


def _hub_penalty_for_path(
    path: RawPath,
    node_degree_map: dict[str, int],
    max_degree: int,
) -> float:
    """Compute the hub penalty factor for a single path.

    penalty = max over intermediate nodes of: log(degree, 2) / log(max_degree, 2)

    Returns 0.0 when max_degree <= 2 (no meaningful hub) or when there are no
    intermediate nodes (2-hop paths with a single intermediate still apply the
    formula correctly).

    The penalty is always in [0, 1]:
      - degree == 1 → log(max(1,2)) = 0 → penalty = 0 (no penalty)
      - degree == max_degree → log(d)/log(d) = 1 → penalty = 1 (maximum)

    The penalised composite = composite / (1 + penalty), so:
      - penalty = 0 → no change
      - penalty = 1 → composite halved
    """
    if max_degree <= 2:
        return 0.0

    log_max = math.log(max_degree)
    intermediates = path.node_ids[1:-1]
    if not intermediates:
        return 0.0

    max_pen = 0.0
    for nid in intermediates:
        degree = node_degree_map.get(nid, 1)
        # Clamp degree to at least 2 to avoid log(1) = 0 skewing the ratio.
        pen = math.log(max(degree, 2)) / log_max
        if pen > max_pen:
            max_pen = pen
    return max_pen


def _composite(
    harmonic: float,
    diversity: float,
    surprise: float,
    template_match: str | None,
    hub_penalty: float = 0.0,
) -> float:
    """Compute the composite score, clamped to [0, 1] and rounded to 6dp.

    hub_penalty (default 0.0) reduces the score for paths through high-degree
    hub entities.  The final result is divided by (1 + hub_penalty) before
    rounding and clamping.
    """
    raw = harmonic * 0.4 + diversity * 0.35 + surprise * 0.25 + (0.1 if template_match else 0.0)
    penalised = raw / (1.0 + hub_penalty)
    return round(min(penalised, 1.0), 6)


class PathScorer:
    """Score a single RawPath relative to all candidate paths for an anchor.

    Usage::

        scorer = PathScorer()
        insights = [scorer.score(p, all_paths) for p in all_paths]

    Args:
    ----
        template_match: Pre-computed template name for the path (or None).
                        Callers should pass the result of PathTemplateMatcher.match().

    Hub penalty (2026-05-23):
        When ``score()`` is called, a node_degree_map is derived from all_paths
        by counting how many paths each intermediate node appears in.  Paths
        through high-frequency hub nodes (e.g. "Artificial Intelligence" with
        127 edges) are penalised proportionally to log(degree)/log(max_degree),
        so company-specific paths maintain ranking separation.
    """

    def score(
        self,
        raw_path: RawPath,
        all_paths: list[RawPath],
        template_match: str | None = None,
        node_degree_map: dict[str, int] | None = None,
        max_degree: int | None = None,
    ) -> PathInsight:
        """Convert a RawPath to a fully-scored PathInsight.

        Args:
        ----
            raw_path:      The path to score.
            all_paths:     All candidate paths for the same anchor (used for
                           surprise score and hub penalty computation).
            template_match: Optional template name matched by PathTemplateMatcher.
            node_degree_map: Pre-computed {node_id: path_occurrence_count} for
                           the full all_paths set.  When None, computed here from
                           all_paths (callers that process many paths should
                           pre-compute this once and pass it in for efficiency).
            max_degree:    Maximum value in node_degree_map (pre-computed for
                           efficiency).  When None, derived from node_degree_map.

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
        # ``forward`` carries per-edge traversal orientation for correct rendering
        # (direction-agnostic for scoring — no sub-score reads it).  Missing entry
        # (legacy RawPath) defaults to forward.
        edges = tuple(
            PathEdge(
                relation_type=str(rt),
                confidence=float(conf),
                forward=_forward_at(raw_path.edge_forward, i),
            )
            for i, (rt, conf) in enumerate(zip(raw_path.rel_types, raw_path.edge_confs, strict=False))
        )

        harmonic = _harmonic_mean(raw_path.edge_confs)
        diversity = _diversity_score(raw_path.node_types, hop_count)
        surprise = _surprise_score(raw_path.rel_types, all_paths)

        # Hub penalty: computed from the path-occurrence counts of intermediate
        # nodes across all_paths.  Pre-compute once per batch for efficiency;
        # callers in PathInsightWorker pass pre-computed values.
        if node_degree_map is None:
            node_degree_map = _build_node_degree_map(all_paths)
        _max_degree = max_degree if max_degree is not None else (max(node_degree_map.values(), default=1))
        hub_penalty = _hub_penalty_for_path(raw_path, node_degree_map, _max_degree)

        composite = _composite(harmonic, diversity, surprise, template_match, hub_penalty)

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
            hub_penalty=round(hub_penalty, 6),
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
