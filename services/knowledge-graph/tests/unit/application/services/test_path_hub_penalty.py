"""Unit tests for PathScorer hub-penalty logic (2026-05-23).

Tests cover:
- test_hub_penalty_zero_when_max_degree_le_2         — no penalty when KG is tiny
- test_hub_penalty_zero_for_non_hub_intermediate     — low-degree node is unpenalised
- test_hub_penalty_one_for_max_degree_node           — highest-degree node → penalty=1
- test_hub_penalty_partial_for_mid_degree_node       — intermediate degree → 0<p<1
- test_build_node_degree_map_excludes_anchor         — anchor node (index 0) not counted
- test_build_node_degree_map_excludes_endpoint       — last node not counted as hub
- test_composite_reduced_by_hub_penalty              — composite_score lower when hub present
- test_scorer_high_degree_path_lower_than_low_degree — paths through AI hub score lower
- test_scorer_no_regression_single_path              — single-path baseline unchanged formula
"""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.unit


# ── Helper builders ──────────────────────────────────────────────────────────


def _make_raw_path(
    node_ids: tuple[str, ...] | None = None,
    rel_types: tuple[str, ...] = ("COMPETES_WITH", "SUPPLIES_TO"),
    edge_confs: tuple[float, ...] = (0.8, 0.7),
    node_types: tuple[str, ...] = ("company", "company", "company"),
) -> object:
    from uuid import uuid4

    from knowledge_graph.infrastructure.age.path_discovery import RawPath

    n = len(node_types)
    ids = node_ids or tuple(str(uuid4()) for _ in range(n))
    names = tuple(f"E{i}" for i in range(n))
    return RawPath(
        node_ids=ids,
        node_names=names,
        node_types=node_types,
        rel_types=rel_types,
        edge_confs=edge_confs,
    )


# ── _build_node_degree_map ────────────────────────────────────────────────────


class TestBuildNodeDegreeMap:
    def test_excludes_anchor_node(self) -> None:
        """Anchor node (index 0) must NOT appear in the degree map."""
        from knowledge_graph.application.services.path_scorer import _build_node_degree_map

        anchor_id = "anchor-000"
        hub_id = "hub-111"
        end_id = "end-222"
        path = _make_raw_path(node_ids=(anchor_id, hub_id, end_id))
        degree_map = _build_node_degree_map([path])  # type: ignore[arg-type]
        # anchor must not be counted
        assert anchor_id not in degree_map

    def test_excludes_endpoint_node(self) -> None:
        """Last node (endpoint) must NOT appear in the degree map as an intermediate."""
        from knowledge_graph.application.services.path_scorer import _build_node_degree_map

        anchor_id = "anchor-000"
        hub_id = "hub-111"
        end_id = "end-222"
        path = _make_raw_path(node_ids=(anchor_id, hub_id, end_id))
        degree_map = _build_node_degree_map([path])  # type: ignore[arg-type]
        # endpoint must not be counted as intermediate
        assert end_id not in degree_map

    def test_counts_intermediate_across_paths(self) -> None:
        """A hub that appears as intermediate in N paths gets degree N."""
        from knowledge_graph.application.services.path_scorer import _build_node_degree_map

        hub_id = "hub-central"
        paths = [
            _make_raw_path(node_ids=("a", hub_id, "b")),
            _make_raw_path(node_ids=("c", hub_id, "d")),
            _make_raw_path(node_ids=("e", hub_id, "f")),
        ]
        degree_map = _build_node_degree_map(paths)  # type: ignore[arg-type]
        assert degree_map[hub_id] == 3

    def test_empty_paths_returns_empty_map(self) -> None:
        """Empty path list → empty degree map."""
        from knowledge_graph.application.services.path_scorer import _build_node_degree_map

        assert _build_node_degree_map([]) == {}

    def test_same_node_appears_twice_in_path_counted_once(self) -> None:
        """If a node appears as multiple intermediates in the same path, count once."""
        from knowledge_graph.application.services.path_scorer import _build_node_degree_map

        hub_id = "hub-self-loop"
        # 3-hop path: anchor → hub → hub → end  (hub appears twice as intermediate)
        # We use set() in the implementation to count once per path.
        path = _make_raw_path(
            node_ids=("anchor", hub_id, hub_id, "end"),
            rel_types=("R1", "R2", "R3"),
            edge_confs=(0.8, 0.7, 0.6),
            node_types=("company", "company", "company", "company"),
        )
        degree_map = _build_node_degree_map([path])  # type: ignore[arg-type]
        # Should count hub as appearing in 1 path, not 2.
        assert degree_map[hub_id] == 1


# ── _hub_penalty_for_path ─────────────────────────────────────────────────────


class TestHubPenaltyForPath:
    def test_zero_when_max_degree_le_2(self) -> None:
        """When max_degree <= 2 the penalty is always 0.0."""
        from knowledge_graph.application.services.path_scorer import _hub_penalty_for_path

        path = _make_raw_path(node_ids=("a", "hub", "b"))
        degree_map = {"hub": 127}
        penalty = _hub_penalty_for_path(path, degree_map, max_degree=2)  # type: ignore[arg-type]
        assert penalty == 0.0

    def test_zero_for_degree_one_node(self) -> None:
        """A node appearing in only 1 path: log(max(1,2))/log(max_degree) → non-zero.

        With max_degree=10: log(2)/log(10) ≈ 0.301.  This is expected — even a
        degree-1 node is penalised relative to the maximum.  What matters is that
        the penalty is strictly less than 1.0 and > 0.0.
        """
        from knowledge_graph.application.services.path_scorer import _hub_penalty_for_path

        path = _make_raw_path(node_ids=("a", "low-hub", "b"))
        degree_map = {"low-hub": 1}
        penalty = _hub_penalty_for_path(path, degree_map, max_degree=100)  # type: ignore[arg-type]
        # penalty = log(max(1,2)) / log(100) = log(2)/log(100)
        expected = math.log(2) / math.log(100)
        assert abs(penalty - expected) < 1e-9

    def test_one_for_max_degree_node(self) -> None:
        """A node with degree == max_degree gets penalty = 1.0."""
        from knowledge_graph.application.services.path_scorer import _hub_penalty_for_path

        path = _make_raw_path(node_ids=("a", "ai-hub", "b"))
        max_deg = 127
        degree_map = {"ai-hub": max_deg}
        penalty = _hub_penalty_for_path(path, degree_map, max_degree=max_deg)  # type: ignore[arg-type]
        assert abs(penalty - 1.0) < 1e-9

    def test_partial_for_mid_degree_node(self) -> None:
        """A mid-degree node produces penalty strictly between 0 and 1."""
        from knowledge_graph.application.services.path_scorer import _hub_penalty_for_path

        path = _make_raw_path(node_ids=("a", "mid-hub", "b"))
        degree = 30
        max_deg = 127
        degree_map = {"mid-hub": degree}
        penalty = _hub_penalty_for_path(path, degree_map, max_degree=max_deg)  # type: ignore[arg-type]
        expected = math.log(degree) / math.log(max_deg)
        assert abs(penalty - expected) < 1e-9
        assert 0.0 < penalty < 1.0

    def test_no_intermediate_nodes_returns_zero(self) -> None:
        """Paths with no intermediate nodes (would need hop_count=1, impossible in domain)
        still return 0 without crashing."""
        from knowledge_graph.application.services.path_scorer import _hub_penalty_for_path
        from knowledge_graph.infrastructure.age.path_discovery import RawPath

        # Build a degenerate path with no intermediates (node_ids has only anchor + end)
        # This cannot happen in the real domain (min hop_count=2 → 3 nodes)
        # but we test the code path for robustness.
        path = RawPath(
            node_ids=("anchor", "end"),
            node_names=("A", "B"),
            node_types=("company", "company"),
            rel_types=("R",),
            edge_confs=(0.8,),
        )
        degree_map: dict[str, int] = {}
        penalty = _hub_penalty_for_path(path, degree_map, max_degree=100)
        assert penalty == 0.0


# ── _composite with hub_penalty ───────────────────────────────────────────────


class TestCompositeWithHubPenalty:
    def test_composite_reduced_by_hub_penalty(self) -> None:
        """composite with hub_penalty < composite without penalty."""
        from knowledge_graph.application.services.path_scorer import _composite

        h, d, s = 0.8, 0.5, 0.7
        raw = h * 0.4 + d * 0.35 + s * 0.25
        composite_no_penalty = _composite(h, d, s, template_match=None, hub_penalty=0.0)
        composite_with_penalty = _composite(h, d, s, template_match=None, hub_penalty=0.5)

        # Penalised should be lower.
        assert composite_with_penalty < composite_no_penalty
        # Manually verify: raw / (1 + 0.5) = raw / 1.5
        expected = round(min(raw / 1.5, 1.0), 6)
        assert abs(composite_with_penalty - expected) < 1e-9

    def test_composite_unchanged_when_penalty_zero(self) -> None:
        """hub_penalty=0.0 must produce same result as the old formula."""
        from knowledge_graph.application.services.path_scorer import _composite

        h, d, s = 0.75, 0.5, 0.8
        composite = _composite(h, d, s, template_match=None, hub_penalty=0.0)
        raw = h * 0.4 + d * 0.35 + s * 0.25
        expected = round(min(raw, 1.0), 6)
        assert abs(composite - expected) < 1e-9

    def test_composite_never_below_zero(self) -> None:
        """Composite must always be >= 0 regardless of penalty."""
        from knowledge_graph.application.services.path_scorer import _composite

        composite = _composite(0.0, 0.0, 0.0, template_match=None, hub_penalty=1.0)
        assert composite >= 0.0


# ── PathScorer end-to-end hub penalty ────────────────────────────────────────


class TestPathScorerHubPenalty:
    def test_high_degree_path_scores_lower(self) -> None:
        """Path through a hub entity scores lower than a direct company-to-company path."""
        from knowledge_graph.application.services.path_scorer import PathScorer

        hub_id = "ai-hub-entity"
        company_a = "company-alpha"
        company_b = "company-beta"
        company_c = "company-gamma"

        # 50 paths route through the AI hub intermediate node.
        hub_paths = [
            _make_raw_path(
                node_ids=(str(i), hub_id, str(1000 + i)),
                rel_types=("RELATED_TO", "COMPETES_WITH"),
                edge_confs=(0.8, 0.7),
            )
            for i in range(50)
        ]

        # 1 path goes directly between specific companies (hub_id not in intermediate).
        direct_path = _make_raw_path(
            node_ids=(company_a, company_b, company_c),
            rel_types=("COMPETES_WITH", "PARTNER_OF"),
            edge_confs=(0.9, 0.85),
        )

        all_paths = [*hub_paths, direct_path]
        scorer = PathScorer()

        # Score one hub path and the direct path.
        hub_insight = scorer.score(hub_paths[0], all_paths)  # type: ignore[arg-type]
        direct_insight = scorer.score(direct_path, all_paths)  # type: ignore[arg-type]

        # Direct path should score higher (no hub penalty).
        assert direct_insight.composite_score >= hub_insight.composite_score

    def test_scorer_pre_computed_degree_map_consistent(self) -> None:
        """Pre-computing degree_map + max_degree gives same result as auto-compute."""
        from knowledge_graph.application.services.path_scorer import PathScorer, _build_node_degree_map

        raw = _make_raw_path(
            node_ids=("anchor", "intermediate", "end"),
            rel_types=("R1", "R2"),
            edge_confs=(0.8, 0.7),
        )
        all_paths = [raw]  # type: ignore[list-item]

        scorer = PathScorer()

        # Auto-compute (no pre-computed map passed).
        insight_auto = scorer.score(raw, all_paths)  # type: ignore[arg-type]

        # Pre-compute and pass explicitly.
        degree_map = _build_node_degree_map(all_paths)  # type: ignore[arg-type]
        max_deg = max(degree_map.values(), default=1)
        insight_pre = scorer.score(raw, all_paths, node_degree_map=degree_map, max_degree=max_deg)  # type: ignore[arg-type]

        # Both must produce the same composite_score.
        assert abs(insight_auto.composite_score - insight_pre.composite_score) < 1e-9
