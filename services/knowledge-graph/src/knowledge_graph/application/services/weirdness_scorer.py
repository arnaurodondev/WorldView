"""WeirdnessScorer — the per-path weirdness metric (PLAN-0112 T-3-03, FR-4).

Pure application-layer service: NO infrastructure imports (mirrors the old
``PathScorer``).  It supersedes ``PathScorer``'s saturated local-frequency
``surprise_score`` with a per-path score computed from graph-GLOBAL statistics,
so each path is scored independently of the (slow) full enumeration.

Formula (§6.5):

    weirdness = reliability x (w_U*U + w_S*S + w_N*N)        clamped to [0, 1]

where, for a RawPath with edges (u_i → v_i):
  • reliability (R)        = harmonic_mean(edge_confs)            — multiplicative
                             gate so a high-surprise path on extraction noise
                             cannot win (zeros clamped to 1e-6).
  • unexpectedness (U)     = mean over edges of surprise_edge(u, v):
        config_model: clamp01( -log( min(1, deg(u)*deg(v)/(2m)) ) / NORM )
                      with m = graph_stats.total_edges, NORM = -log(1/(2m)).
                      High-degree endpoints ⇒ low surprise (hub demotion —
                      replaces the hand-tuned hub_penalty).
        adamic_adar:  mean over edges of 1/log(deg) of the SHARED vertex between
                      consecutive edges (rare shared neighbours ⇒ high surprise),
                      normalised to [0, 1].  Selected by config (AD-3).
  • semantic_distance (S)  = clamp01( (1 - cosine(emb(src), emb(dst))) / 2 );
                             missing embedding → entity_type fallback
                             (1.0 different type, 0.3 same) + scorer_version
                             suffix "+typefallback".
  • novelty (N)            = fraction of rel_ids whose first_seen is within
                             ``novelty_window_days``.

Self-loop / non-distinct-endpoint paths return ``weirdness = 0`` (filtered before
persist) — the entity stays a dumb record, the invariant lives here.

Injected pure lookups (so the scorer never touches the DB):
  degree_of(entity_id) -> int               undirected degree (missing → 1, max surprise, fail-open)
  meaningful_degree_of(entity_id) -> int     degree excluding membership edges
  graph_stats() -> GraphStats                the 2m normaliser term
  embedding_of(entity_id) -> Sequence|None   definition-view vector (None → type fallback)
  first_seen_of(rel_id) -> datetime|None     relations.first_evidence_at
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.domain.entities.path_insight import (
    PathEdge,
    PathInsight,
    PathNode,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime, timedelta
    from uuid import UUID

    from knowledge_graph.application.ports.graph_path_engine import RawPath
    from knowledge_graph.application.ports.node_degree_repository import GraphStats

# Base scorer-version stamp (NFR-6 reproducibility).  The type-fallback suffix is
# appended when any endpoint embedding was missing.
_SCORER_VERSION = "weirdness-1.0"

# Default composite weights (overridable via constructor / config).
_DEFAULT_W_UNEXPECTEDNESS = 0.45
_DEFAULT_W_SEMANTIC = 0.40
_DEFAULT_W_NOVELTY = 0.15

# entity_type semantic-distance fallback when an endpoint embedding is missing.
_TYPE_FALLBACK_DIFFERENT = 1.0
_TYPE_FALLBACK_SAME = 0.3


def _clamp01(value: float) -> float:
    """Clamp a float to the closed unit interval [0, 1]."""
    return max(0.0, min(1.0, value))


def _harmonic_mean(values: tuple[float, ...]) -> float:
    """Harmonic mean of ``values``, clamping zeros to 1e-6 (R-gate)."""
    if not values:
        return 0.0
    clamped = tuple(max(v, 1e-6) for v in values)
    return len(clamped) / sum(1.0 / v for v in clamped)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 on a zero vector."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class WeirdnessScorer:
    """Score a single RawPath into a fully-populated weirdness PathInsight (FR-4).

    Pure: all graph data arrives via the injected lookups.  Construct once per
    worker cycle (the worker pre-fetches degrees/embeddings/first_seen into
    closures) and call :meth:`score` per path.
    """

    def __init__(
        self,
        *,
        degree_of: Callable[[UUID], int],
        meaningful_degree_of: Callable[[UUID], int],
        graph_stats: GraphStats,
        embedding_of: Callable[[UUID], Sequence[float] | None],
        first_seen_of: Callable[[UUID], datetime | None],
        novelty_window: timedelta,
        w_unexpectedness: float = _DEFAULT_W_UNEXPECTEDNESS,
        w_semantic: float = _DEFAULT_W_SEMANTIC,
        w_novelty: float = _DEFAULT_W_NOVELTY,
        unexpectedness_mode: str = "config_model",
    ) -> None:
        self._degree_of = degree_of
        self._meaningful_degree_of = meaningful_degree_of
        self._stats = graph_stats
        self._embedding_of = embedding_of
        self._first_seen_of = first_seen_of
        self._novelty_window = novelty_window
        self._w_u = w_unexpectedness
        self._w_s = w_semantic
        self._w_n = w_novelty
        self._mode = unexpectedness_mode

    # ── Public API ────────────────────────────────────────────────────────────

    def score(self, raw_path: RawPath) -> PathInsight:
        """Convert a RawPath into a fully-scored weirdness PathInsight."""
        nodes = tuple(
            PathNode(entity_id=_parse_uuid(nid), name=str(nn), entity_type=str(nt))
            for nid, nn, nt in zip(raw_path.node_ids, raw_path.node_names, raw_path.node_types, strict=False)
        )
        edges = tuple(
            PathEdge(relation_type=str(rt), confidence=_clamp01(float(conf)))
            for rt, conf in zip(raw_path.rel_types, raw_path.edge_confs, strict=False)
        )

        anchor_id = nodes[0].entity_id if nodes else new_uuid7()
        dst_id = nodes[-1].entity_id if nodes else None

        # Self-loop / non-distinct-endpoint guard: weirdness 0 (filtered before
        # persist).  Distinct ALL node ids — a repeated intermediate is also a
        # degenerate cycle for "weird connection" purposes.
        distinct = len({n.entity_id for n in nodes}) == len(nodes)
        if not distinct or len(nodes) < 2:
            return self._zeroed(raw_path, nodes, edges, anchor_id, dst_id)

        reliability = _harmonic_mean(raw_path.edge_confs)
        unexpectedness = self._unexpectedness(raw_path)
        semantic_distance, type_fallback = self._semantic_distance(nodes[0], nodes[-1])
        novelty = self._novelty(raw_path)

        weirdness = _clamp01(
            reliability * (self._w_u * unexpectedness + self._w_s * semantic_distance + self._w_n * novelty)
        )

        scorer_version = _SCORER_VERSION + ("+typefallback" if type_fallback else "")

        return PathInsight(
            insight_id=new_uuid7(),
            anchor_entity_id=anchor_id,
            hop_count=raw_path.hop_count,
            path_nodes=nodes,
            path_edges=edges,
            # Deprecated fields retained for back-compat; not populated meaningfully.
            harmonic_score=round(reliability, 6),
            diversity_score=0.0,
            surprise_score=round(unexpectedness, 6),
            # composite_score mirrors weirdness so the existing ranking/index works.
            composite_score=round(weirdness, 6),
            computed_at=utc_now(),
            dst_entity_id=dst_id,
            reliability=round(reliability, 6),
            unexpectedness=round(unexpectedness, 6),
            semantic_distance=round(semantic_distance, 6),
            novelty=round(novelty, 6),
            weirdness=round(weirdness, 6),
            scorer_version=scorer_version,
        )

    # ── Sub-scores ────────────────────────────────────────────────────────────

    def _unexpectedness(self, raw_path: RawPath) -> float:
        """Mean per-edge surprise (config-model or Adamic-Adar)."""
        node_ids = [_parse_uuid(nid) for nid in raw_path.node_ids]
        if len(node_ids) < 2:
            return 0.0
        if self._mode == "adamic_adar":
            return self._unexpectedness_adamic_adar(node_ids)
        return self._unexpectedness_config_model(node_ids)

    def _unexpectedness_config_model(self, node_ids: list[UUID]) -> float:
        """Configuration-model surprise: -log(min(1, deg(u)*deg(v)/2m)) / NORM.

        ``2m`` = 2 x total_edges.  NORM = -log(1/2m) is the maximum possible
        surprise (when deg(u)=deg(v)=1), so the term is normalised to [0, 1].
        Missing degree → 1 (fail-open to "weird", logged upstream).
        """
        two_m = 2 * max(self._stats.total_edges, 1)
        norm = -math.log(1.0 / two_m) if two_m > 1 else 1.0
        if norm <= 0.0:
            return 0.0
        surprises: list[float] = []
        for u, v in itertools.pairwise(node_ids):
            deg_u = max(self._safe_degree(u), 1)
            deg_v = max(self._safe_degree(v), 1)
            ratio = min(1.0, (deg_u * deg_v) / two_m)
            surprise = _clamp01(-math.log(ratio) / norm)
            surprises.append(surprise)
        return sum(surprises) / len(surprises) if surprises else 0.0

    def _unexpectedness_adamic_adar(self, node_ids: list[UUID]) -> float:
        """Adamic-Adar style surprise on the SHARED vertex between consecutive
        edges: rare (low-degree) bridge vertices ⇒ high surprise.

        For a path a-b-c the shared vertex of edges (a,b) and (b,c) is ``b``; a
        low-degree ``b`` means few paths route through it → surprising.  We map
        1/log(deg(b)) to [0, 1] against the graph max degree (log scale).
        """
        log_max = math.log(max(self._stats.max_degree, 2))
        scores: list[float] = []
        for mid in node_ids[1:-1]:  # interior (bridge) vertices
            deg = max(self._safe_degree(mid), 2)
            # 1/log(deg) is high for low-degree bridges; normalise vs 1/log(2).
            aa = (1.0 / math.log(deg)) / (1.0 / math.log(2))
            # also fold in the inverse against max so big hubs ⇒ ~0
            scaled = _clamp01(1.0 - (math.log(deg) / log_max)) if log_max > 0 else aa
            scores.append(_clamp01((aa + scaled) / 2.0))
        # Endpoints-only path (2-hop has one interior vertex); fall back to
        # config-model when there are no interior vertices.
        if not scores:
            return self._unexpectedness_config_model(node_ids)
        return sum(scores) / len(scores)

    def _semantic_distance(self, src: PathNode, dst: PathNode) -> tuple[float, bool]:
        """Endpoint cosine distance, normalised [0, 1]; (value, used_type_fallback)."""
        emb_src = self._embedding_of(src.entity_id)
        emb_dst = self._embedding_of(dst.entity_id)
        if emb_src is not None and emb_dst is not None and len(emb_src) == len(emb_dst) and len(emb_src) > 0:
            cosine = _cosine(emb_src, emb_dst)
            return _clamp01((1.0 - cosine) / 2.0), False
        # entity_type fallback (1.0 different / 0.3 same) — never crashes.
        fallback = _TYPE_FALLBACK_DIFFERENT if src.entity_type != dst.entity_type else _TYPE_FALLBACK_SAME
        return fallback, True

    def _novelty(self, raw_path: RawPath) -> float:
        """Fraction of edges whose first_evidence_at is within the novelty window."""
        rel_ids = raw_path.rel_ids
        if not rel_ids:
            return 0.0
        cutoff = utc_now() - self._novelty_window  # type: ignore[no-any-return]
        recent = 0
        for rid in rel_ids:
            first_seen = self._first_seen_of(rid)
            if first_seen is not None and first_seen >= cutoff:
                recent += 1
        return recent / len(rel_ids)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _safe_degree(self, entity_id: UUID) -> int:
        """Degree lookup with fail-open: missing ⇒ 1 (max surprise)."""
        try:
            deg = self._degree_of(entity_id)
        except Exception:
            return 1
        return deg if deg and deg > 0 else 1

    def _zeroed(
        self,
        raw_path: RawPath,
        nodes: tuple[PathNode, ...],
        edges: tuple[PathEdge, ...],
        anchor_id: UUID,
        dst_id: UUID | None,
    ) -> PathInsight:
        """Build a weirdness=0 PathInsight for a self-loop / degenerate path."""
        return PathInsight(
            insight_id=new_uuid7(),
            anchor_entity_id=anchor_id,
            hop_count=raw_path.hop_count,
            path_nodes=nodes,
            path_edges=edges,
            harmonic_score=0.0,
            diversity_score=0.0,
            surprise_score=0.0,
            composite_score=0.0,
            computed_at=utc_now(),
            dst_entity_id=dst_id,
            reliability=0.0,
            unexpectedness=0.0,
            semantic_distance=0.0,
            novelty=0.0,
            weirdness=0.0,
            scorer_version=_SCORER_VERSION,
        )


def _parse_uuid(value: object) -> UUID:
    """Parse a UUID from a string, returning a fresh UUIDv7 on failure."""
    from uuid import UUID as _UUID

    try:
        return _UUID(str(value))
    except (ValueError, AttributeError):
        return new_uuid7()
