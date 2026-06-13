"""FindPathsBetweenUseCase — on-demand pairwise pathfinding (PLAN-0112 W4, T-4-01).

Answers "is entity A connected to entity B, and how?" by reusing the consolidated
``GraphPathEngine`` (the W2 staged-VLE engine, BP-687) plus the W3
``WeirdnessScorer``.  The flow (PRD §6.7 — pairwise):

  1. Validate ``source != target``, both entities exist, ``max_hops`` in range.
  2. ``GraphPathEngine.path_exists(source, target, max_hops)`` → shortest hop
     count (or None).  When None: ``connected=False``, no paths, done.
  3. ``GraphPathEngine.find_paths_between(...)`` (membership pruned unless
     ``meaningful_only`` is False) → up to ``limit`` shortest raw paths.
  4. Score every raw path with the ``WeirdnessScorer`` (built from the SAME
     prefetch lookups the ``PathInsightWorker`` uses — degree map, graph stats,
     definition embeddings, first-seen timestamps).
  5. Rank by ``weirdness`` desc, tie-broken by ``hop_count`` asc; return up to
     ``limit``.

Architecture (R25): this is an application-layer use case.  It depends on the
``GraphPathEngine`` port (ABC), an injected ``entity_exists`` callable, and an
injected ``build_scorer`` async factory — never on the AGE adapter or any
infrastructure repository directly.  All AGE-session + prefetch SQL lives behind
those injections.

R27 exception: ``GraphPathEngine`` runs AGE traversal which requires
``LOAD 'age'`` → it holds its own WRITE session factory (documented exception,
same precedent as ``CypherPathUseCase`` / ``AgeGraphPathEngine``).  The use case
itself opens no session.

Timeout: an AGE statement-timeout surfaces as ``CypherTimeoutError`` from the
engine; the router maps it to HTTP 503 with a retry hint (PRD §6.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.graph_path_engine import edge_forward_at as _forward_at
from knowledge_graph.domain.errors import KnowledgeGraphError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine, RawPath
    from knowledge_graph.application.schemas.paths import PathsBetweenResponse
    from knowledge_graph.application.services.weirdness_scorer import WeirdnessScorer

# Validation bounds (PRD §6.2).  ``max_hops`` upper bound is the configured cap
# (``Settings.path_max_hops`` = 3, RESOLVED OQ-3); ``limit`` is [1, 20].
_LIMIT_MIN = 1
_LIMIT_MAX = 20


class PathsBetweenSameEntityError(KnowledgeGraphError):
    """Raised when ``source`` and ``target`` are the same entity (→ HTTP 400)."""


class PathsBetweenEntityNotFoundError(KnowledgeGraphError):
    """Raised when ``source`` or ``target`` does not exist (→ HTTP 404)."""

    def __init__(self, entity_id: UUID) -> None:
        super().__init__(f"Entity not found: {entity_id}")
        self.entity_id = entity_id


class FindPathsBetweenUseCase:
    """Find ranked paths between two bound endpoints on demand (FR-8).

    Args:
    ----
        path_engine: ``GraphPathEngine`` port (AGE-backed adapter injected).  Holds
            its own write session factory for ``LOAD 'age'`` (R27 exception).
        entity_exists: Async callable ``(UUID) -> bool`` checking canonical
            existence (wired in ``dependencies.py``; read session).
        build_scorer: Async factory ``(list[RawPath]) -> WeirdnessScorer`` that
            pre-fetches the global lookups (degree map / graph stats / definition
            embeddings / first-seen) for exactly the entities + relations on the
            given paths and returns a fully-configured pure scorer.  Mirrors
            ``PathInsightWorker._score_with_weirdness`` so pairwise + batch share
            the identical scoring semantics.  ``None`` degrades to unscored
            (sub-scores 0.0) — used before W3 wiring / in minimal harnesses.
        max_hops_cap: Hard upper bound for ``max_hops`` (``Settings.path_max_hops``).

    """

    def __init__(
        self,
        path_engine: GraphPathEngine,
        entity_exists: Callable[[UUID], Awaitable[bool]],
        build_scorer: Callable[[list[RawPath]], Awaitable[WeirdnessScorer]] | None = None,
        max_hops_cap: int = 3,
    ) -> None:
        self._engine = path_engine
        self._entity_exists = entity_exists
        self._build_scorer = build_scorer
        self._max_hops_cap = max_hops_cap

    async def execute(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int = 3,
        limit: int = 5,
        meaningful_only: bool = False,
    ) -> PathsBetweenResponse:
        """Return ranked pairwise paths between ``source`` and ``target``.

        Contract self-consistency (live-QA fix 2026-06-13)
        --------------------------------------------------
        ``connected`` and ``shortest_hops`` are derived from the SAME enumerated
        + filtered path set the endpoint actually returns — NOT from a separate,
        looser ``path_exists`` probe.  ``path_exists`` is kept only as a cheap
        short-circuit for the truly-disconnected case (returns None → fast empty
        exit).  But ``path_exists`` can count a short path that
        ``find_paths_between`` then correctly drops via its distinct-node /
        self-loop guard (``id(s) <> id(t)`` + node-id dedup): these degenerate
        paths route through DUPLICATE canonical vertices (the deferred FR-11
        entity-dedup — e.g. SpaceX has a duplicate).  Reporting
        ``connected=true, shortest_hops=2, paths=[]`` in that case is a
        contradiction.  So when enumeration yields zero REPORTABLE paths we
        report ``connected=False, shortest_hops=None, paths=[]`` — "no reportable
        connection" — even though ``path_exists`` saw a (degenerate) path.  A
        pair connected ONLY through duplicate-entity self-loops is therefore
        reported as not-connected until FR-11 dedup lands.  When reportable paths
        DO exist, ``shortest_hops = min(hop_count)`` over those paths.

        Raises
        ------
            PathsBetweenSameEntityError: ``source == target`` (→ 400).
            PathsBetweenEntityNotFoundError: an endpoint is missing (→ 404).
            ValueError: ``max_hops`` / ``limit`` out of range (→ 422).
            CypherTimeoutError: AGE traversal exceeded statement_timeout (→ 503).

        """
        # ── Validation ──────────────────────────────────────────────────────
        if source == target:
            msg = "source and target must be different entities"
            raise PathsBetweenSameEntityError(msg)
        self._validate_bounds(max_hops, limit)
        if not await self._entity_exists(source):
            raise PathsBetweenEntityNotFoundError(source)
        if not await self._entity_exists(target):
            raise PathsBetweenEntityNotFoundError(target)

        # Imports deferred to keep the module import-light (and avoid the
        # application→schema cycle at load time).
        from knowledge_graph.application.schemas.paths import (
            PathBetweenPublic,
            PathEdgePublic,
            PathNodePublic,
            PathsBetweenResponse,
        )

        # ── Cheap short-circuit: truly disconnected within max_hops? ────────
        # ``path_exists`` is a fast staged-VLE probe (BP-687).  None ⇒ no path at
        # all ⇒ fast empty exit.  A non-None result is NOT trusted for the
        # response ``shortest_hops`` — it can count a degenerate duplicate-vertex
        # path that the enumeration below drops (see docstring); the reportable
        # ``connected`` / ``shortest_hops`` are derived from ``scored`` instead.
        probe_hops = await self._engine.path_exists(source, target, max_hops=max_hops)
        if probe_hops is None:
            # Disconnected within max_hops — no paths, shortest_hops null.
            return PathsBetweenResponse(
                source_entity_id=source,
                target_entity_id=target,
                connected=False,
                shortest_hops=None,
                paths=[],
                computed_at=utc_now(),
            )

        # ── Enumerate shortest paths (membership-pruned unless meaningful_only
        # is False — note the engine flag is INVERTED: prune when NOT
        # meaningful_only would keep noise; the PRD semantics are
        # "meaningful_only=True ⇒ prune membership edges").
        raw_paths = await self._engine.find_paths_between(
            source,
            target,
            max_hops=max_hops,
            prune_membership=meaningful_only,
            limit=limit,
        )

        # ── Score each path with the WeirdnessScorer (same prefetch as worker) ─
        scored: list[PathBetweenPublic] = []
        scorer = await self._build_scorer(raw_paths) if (self._build_scorer is not None and raw_paths) else None
        for raw in raw_paths:
            if scorer is not None:
                insight = scorer.score(raw)
                reliability = insight.reliability
                unexpectedness = insight.unexpectedness
                semantic_distance = insight.semantic_distance
                novelty = insight.novelty
                weirdness = insight.weirdness
            else:
                # Degrade-to-unscored (pre-W3 / minimal harness): zeros, never crash.
                reliability = unexpectedness = semantic_distance = novelty = weirdness = 0.0
            scored.append(
                PathBetweenPublic(
                    path_nodes=[
                        PathNodePublic(entity_id=UUID(nid), name=name, entity_type=etype)
                        for nid, name, etype in zip(raw.node_ids, raw.node_names, raw.node_types, strict=False)
                    ],
                    path_edges=[
                        PathEdgePublic(
                            relation_type=rt,
                            confidence=float(conf),
                            forward=_forward_at(raw.edge_forward, i),
                        )
                        for i, (rt, conf) in enumerate(zip(raw.rel_types, raw.edge_confs, strict=False))
                    ],
                    hop_count=raw.hop_count,
                    reliability=reliability,
                    unexpectedness=unexpectedness,
                    semantic_distance=semantic_distance,
                    novelty=novelty,
                    weirdness=weirdness,
                )
            )

        # ── Rank: weirdness desc, then hop_count asc (PRD §6.2) ─────────────
        scored.sort(key=lambda p: (-p.weirdness, p.hop_count))
        ranked = scored[:limit]

        # ── Derive connected / shortest_hops from the REPORTABLE path set ───
        # If enumeration dropped every candidate (e.g. ``path_exists`` only saw a
        # degenerate duplicate-vertex path), report "no reportable connection"
        # so the contract is self-consistent (no ``connected:true, paths:[]``).
        if not ranked:
            return PathsBetweenResponse(
                source_entity_id=source,
                target_entity_id=target,
                connected=False,
                shortest_hops=None,
                paths=[],
                computed_at=utc_now(),
            )

        shortest_hops = min(p.hop_count for p in ranked)
        return PathsBetweenResponse(
            source_entity_id=source,
            target_entity_id=target,
            connected=True,
            shortest_hops=shortest_hops,
            paths=ranked,
            computed_at=utc_now(),
        )

    # ── Internals ───────────────────────────────────────────────────────────

    def _validate_bounds(self, max_hops: int, limit: int) -> None:
        """Raise ValueError (→ 422) for out-of-range ``max_hops`` / ``limit``."""
        if not (1 <= max_hops <= self._max_hops_cap):
            msg = f"max_hops must be between 1 and {self._max_hops_cap}; got {max_hops!r}"
            raise ValueError(msg)
        if not (_LIMIT_MIN <= limit <= _LIMIT_MAX):
            msg = f"limit must be between {_LIMIT_MIN} and {_LIMIT_MAX}; got {limit!r}"
            raise ValueError(msg)
