"""Unit tests for WeirdnessScorer (PLAN-0112 T-3-03).

Covers the five sub-scores, hub demotion, self-loop zeroing, config-driven
weights, the entity_type embedding fallback + scorer-version stamp, and the
Adamic-Adar mode switch.  The scorer is PURE — all graph data is injected via
plain callables, so these tests need no DB.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from knowledge_graph.application.ports.graph_path_engine import RawPath
from knowledge_graph.application.ports.node_degree_repository import GraphStats
from knowledge_graph.application.services.weirdness_scorer import WeirdnessScorer

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_A = UUID("01900000-0000-7000-8000-0000000000a1")
_B = UUID("01900000-0000-7000-8000-0000000000b2")
_C = UUID("01900000-0000-7000-8000-0000000000c3")
_R1 = UUID("01900000-0000-7000-8000-0000000000d4")
_R2 = UUID("01900000-0000-7000-8000-0000000000e5")


def _raw_path(
    *,
    node_ids: tuple[str, ...],
    node_types: tuple[str, ...],
    edge_confs: tuple[float, ...],
    rel_ids: tuple[UUID, ...] = (),
    rel_types: tuple[str, ...] | None = None,
) -> RawPath:
    n = len(node_ids)
    rel_types = rel_types or tuple("RELATED_TO" for _ in range(n - 1))
    return RawPath(
        node_ids=node_ids,
        node_names=tuple(f"E{i}" for i in range(n)),
        node_types=node_types,
        rel_types=rel_types,
        edge_confs=edge_confs,
        rel_ids=rel_ids,
    )


def _scorer(
    *,
    degrees: dict[UUID, int],
    stats: GraphStats,
    embeddings: dict[UUID, list[float]] | None = None,
    first_seen: dict[UUID, object] | None = None,
    novelty_days: int = 7,
    mode: str = "config_model",
) -> WeirdnessScorer:
    embeddings = embeddings or {}
    first_seen = first_seen or {}
    return WeirdnessScorer(
        degree_of=lambda eid: degrees.get(eid, 1),
        meaningful_degree_of=lambda eid: degrees.get(eid, 1),
        graph_stats=stats,
        embedding_of=lambda eid: embeddings.get(eid),
        first_seen_of=lambda rid: first_seen.get(rid),  # type: ignore[return-value]
        novelty_window=timedelta(days=novelty_days),
        unexpectedness_mode=mode,
    )


# ── reliability ────────────────────────────────────────────────────────────


def test_reliability_is_harmonic_mean_of_edge_confs() -> None:
    scorer = _scorer(degrees={_A: 2, _B: 2, _C: 2}, stats=GraphStats(100, 100, 10))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),
        edge_confs=(0.5, 1.0),
    )
    insight = scorer.score(rp)
    # harmonic mean of (0.5, 1.0) = 2 / (2 + 1) = 0.6667
    assert insight.reliability == pytest.approx(2 / 3, abs=1e-4)


# ── unexpectedness (hub demotion) ─────────────────────────────────────────


def test_low_degree_endpoints_more_surprising_than_hubs() -> None:
    stats = GraphStats(total_edges=1000, total_meaningful_edges=1000, max_degree=500)
    leaf = _scorer(degrees={_A: 1, _B: 1, _C: 1}, stats=stats)
    hub = _scorer(degrees={_A: 500, _B: 500, _C: 500}, stats=stats)
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "org", "org"),
        edge_confs=(1.0, 1.0),
    )
    leaf_u = leaf.score(rp).unexpectedness
    hub_u = hub.score(rp).unexpectedness
    assert leaf_u > hub_u, "low-degree path must be more unexpected than a hub-routed one"
    assert 0.0 <= hub_u <= 1.0 and 0.0 <= leaf_u <= 1.0


def test_unexpectedness_in_unit_interval() -> None:
    scorer = _scorer(degrees={_A: 3, _B: 7, _C: 2}, stats=GraphStats(50, 50, 7))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "org"),
        edge_confs=(0.9, 0.8),
    )
    assert 0.0 <= scorer.score(rp).unexpectedness <= 1.0


# ── semantic_distance + type fallback ──────────────────────────────────────


def test_semantic_distance_from_embeddings() -> None:
    # Orthogonal endpoints → cosine 0 → distance (1-0)/2 = 0.5.
    embeddings = {_A: [1.0, 0.0], _C: [0.0, 1.0]}
    scorer = _scorer(degrees={_A: 2, _B: 2, _C: 2}, stats=GraphStats(100, 100, 10), embeddings=embeddings)
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "org", "org"),
        edge_confs=(1.0, 1.0),
    )
    insight = scorer.score(rp)
    assert insight.semantic_distance == pytest.approx(0.5, abs=1e-6)
    assert insight.scorer_version == "weirdness-1.0"  # no fallback


def test_missing_embedding_uses_type_fallback_and_stamps_version() -> None:
    scorer = _scorer(degrees={_A: 2, _B: 2, _C: 2}, stats=GraphStats(100, 100, 10), embeddings={})
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),  # endpoints differ → 1.0
        edge_confs=(1.0, 1.0),
    )
    insight = scorer.score(rp)
    assert insight.semantic_distance == pytest.approx(1.0)
    assert insight.scorer_version == "weirdness-1.0+typefallback"


def test_same_type_fallback_is_lower() -> None:
    scorer = _scorer(degrees={_A: 2, _B: 2, _C: 2}, stats=GraphStats(100, 100, 10), embeddings={})
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "org"),  # endpoints same → 0.3
        edge_confs=(1.0, 1.0),
    )
    assert scorer.score(rp).semantic_distance == pytest.approx(0.3)


# ── novelty ────────────────────────────────────────────────────────────────


def test_novelty_fraction_of_recent_edges() -> None:
    now = utc_now()
    first_seen = {
        _R1: now - timedelta(days=1),  # recent
        _R2: now - timedelta(days=30),  # old
    }
    scorer = _scorer(
        degrees={_A: 2, _B: 2, _C: 2},
        stats=GraphStats(100, 100, 10),
        first_seen=first_seen,
        novelty_days=7,
    )
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "org", "org"),
        edge_confs=(1.0, 1.0),
        rel_ids=(_R1, _R2),
    )
    assert scorer.score(rp).novelty == pytest.approx(0.5)


def test_novelty_zero_without_rel_ids() -> None:
    scorer = _scorer(degrees={_A: 2, _B: 2, _C: 2}, stats=GraphStats(100, 100, 10))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "org", "org"),
        edge_confs=(1.0, 1.0),
        rel_ids=(),
    )
    assert scorer.score(rp).novelty == 0.0


# ── composite weirdness + invariants ───────────────────────────────────────


def test_weirdness_mirrored_into_composite_score() -> None:
    scorer = _scorer(degrees={_A: 1, _B: 1, _C: 1}, stats=GraphStats(100, 100, 5))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),
        edge_confs=(1.0, 1.0),
    )
    insight = scorer.score(rp)
    assert insight.composite_score == insight.weirdness
    assert 0.0 <= insight.weirdness <= 1.0


def test_config_weights_change_weirdness() -> None:
    common = {"degrees": {_A: 1, _B: 1, _C: 1}, "stats": GraphStats(100, 100, 5)}
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),
        edge_confs=(1.0, 1.0),
    )
    default = _scorer(**common).score(rp).weirdness
    # Bias entirely toward semantic (endpoints differ → S=1.0).
    biased = (
        WeirdnessScorer(
            degree_of=lambda eid: 1,
            meaningful_degree_of=lambda eid: 1,
            graph_stats=GraphStats(100, 100, 5),
            embedding_of=lambda eid: None,
            first_seen_of=lambda rid: None,
            novelty_window=timedelta(days=7),
            w_unexpectedness=0.0,
            w_semantic=1.0,
            w_novelty=0.0,
        )
        .score(rp)
        .weirdness
    )
    assert biased != default


def test_self_loop_zeroes_weirdness() -> None:
    scorer = _scorer(degrees={_A: 1, _B: 1}, stats=GraphStats(100, 100, 5))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_A)),  # endpoints identical
        node_types=("org", "person", "org"),
        edge_confs=(1.0, 1.0),
    )
    insight = scorer.score(rp)
    assert insight.weirdness == 0.0
    assert insight.composite_score == 0.0


def test_scorer_version_stamped() -> None:
    scorer = _scorer(
        degrees={_A: 2, _B: 2, _C: 2},
        stats=GraphStats(100, 100, 10),
        embeddings={_A: [1.0, 0.0], _C: [1.0, 0.0]},
    )
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "org", "org"),
        edge_confs=(1.0, 1.0),
    )
    assert scorer.score(rp).scorer_version == "weirdness-1.0"


def test_adamic_adar_mode_runs_and_in_range() -> None:
    scorer = _scorer(
        degrees={_A: 1, _B: 3, _C: 1},
        stats=GraphStats(100, 100, 50),
        mode="adamic_adar",
    )
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),
        edge_confs=(1.0, 1.0),
    )
    assert 0.0 <= scorer.score(rp).unexpectedness <= 1.0


def test_dst_entity_id_is_last_node() -> None:
    scorer = _scorer(degrees={_A: 1, _B: 1, _C: 1}, stats=GraphStats(100, 100, 5))
    rp = _raw_path(
        node_ids=(str(_A), str(_B), str(_C)),
        node_types=("org", "person", "place"),
        edge_confs=(1.0, 1.0),
    )
    assert scorer.score(rp).dst_entity_id == _C
