"""GlobalWeirdConnectionsUseCase — graph-wide "weird connections" feed (PLAN-0112 W5, T-5-01).

A read-only use case that returns the globally most-surprising precomputed
paths from ``path_insights`` (ranked by ``weirdness`` DESC).  It powers the
analyst-facing "Weird Connections" feed (PRD-0112 FR-7, §6.2).

R25: the router injects this via a ``Depends()`` factory in
``knowledge_graph.api.dependencies`` — the router never imports infrastructure.
R27: pure ``path_insights`` SELECT (no AGE ``LOAD 'age'``) → the bound repo uses
the read-replica session (``ReadOnlyDbSessionDep``).

The endpoint-pair dedup (keep the single highest-weirdness path per distinct
(src, dst) endpoint pair, OQ-6 default) is done in the repository SQL via
``DISTINCT ON``; this use case is a thin orchestration + validation + DTO-mapping
layer over ``PathInsightRepositoryPort.list_global_weird(...)``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.application.ports.path_insight_repository import PathInsightRepositoryPort
    from knowledge_graph.application.schemas.paths import WeirdConnectionsResponse

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Hard limits for query-parameter validation (enforced before the DB call).
# These mirror PRD-0112 §6.2 (GET /api/v1/connections/weird).
_LIMIT_MIN = 1
_LIMIT_MAX = 100
_OFFSET_MIN = 0
_WEIRDNESS_MIN = 0.0
_WEIRDNESS_MAX = 1.0
_SINCE_DAYS_MIN = 1
_SINCE_DAYS_MAX = 365


class GlobalWeirdConnectionsUseCase:
    """Return the globally most-weird connections, deduped by endpoint pair.

    Args:
        path_insight_repo: Repository bound to a **read-only** session (R27).

    """

    def __init__(self, path_insight_repo: PathInsightRepositoryPort) -> None:
        self._repo = path_insight_repo

    async def execute(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        min_weirdness: float = 0.0,
        since_days: int | None = None,
        entity_type: str | None = None,
    ) -> WeirdConnectionsResponse:
        """Fetch and return the ranked global weird-connections feed.

        Validates query parameters before issuing any DB call.  Raises
        ``ValueError`` for invalid combinations — FastAPI converts these to 422.
        """
        # ── Parameter validation ───────────────────────────────────────────
        self._validate_params(limit, offset, min_weirdness, since_days)

        # ── Fetch deduped, ranked paths (READ session — R27) ───────────────
        insights = await self._repo.list_global_weird(
            limit=limit,
            offset=offset,
            min_weirdness=min_weirdness,
            since_days=since_days,
            entity_type=entity_type,
        )

        # ── Build public response objects ──────────────────────────────────
        # Import from the application layer — never from api/ (R12 / LAYER rule).
        from knowledge_graph.application.schemas.paths import (
            PathEdgePublic,
            PathNodePublic,
            WeirdConnectionPublic,
            WeirdConnectionsResponse,
        )

        connections: list[WeirdConnectionPublic] = []
        freshness_candidates: list[datetime] = []

        for insight in insights:
            # dst_entity_id is guaranteed non-NULL by the repo query (it filters
            # ``dst_entity_id IS NOT NULL``), but guard defensively so a stray
            # NULL row never crashes the feed — skip it instead.
            if insight.dst_entity_id is None:
                logger.warning(
                    "weird_connection_missing_dst",
                    insight_id=str(insight.insight_id),
                )
                continue

            connections.append(
                WeirdConnectionPublic(
                    src_entity_id=insight.anchor_entity_id,
                    dst_entity_id=insight.dst_entity_id,
                    hop_count=insight.hop_count,
                    reliability=insight.reliability,
                    unexpectedness=insight.unexpectedness,
                    semantic_distance=insight.semantic_distance,
                    novelty=insight.novelty,
                    weirdness=insight.weirdness,
                    path_nodes=[
                        PathNodePublic(
                            entity_id=node.entity_id,
                            name=node.name,
                            entity_type=node.entity_type,
                        )
                        for node in insight.path_nodes
                    ],
                    path_edges=[
                        PathEdgePublic(
                            relation_type=edge.relation_type,
                            confidence=edge.confidence,
                            forward=edge.forward,
                        )
                        for edge in insight.path_edges
                    ],
                    computed_at=insight.computed_at,
                )
            )
            freshness_candidates.append(insight.computed_at)

        # freshness_ts = MAX(computed_at) across the returned connections.
        freshness_ts: datetime | None = max(freshness_candidates) if freshness_candidates else None

        return WeirdConnectionsResponse(
            connections=connections,
            total=len(connections),
            freshness_ts=freshness_ts,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_params(
        limit: int,
        offset: int,
        min_weirdness: float,
        since_days: int | None,
    ) -> None:
        """Raise ValueError for any invalid parameter combination (→ HTTP 422)."""
        if not (_LIMIT_MIN <= limit <= _LIMIT_MAX):
            msg = f"limit must be between {_LIMIT_MIN} and {_LIMIT_MAX}; got {limit!r}"
            raise ValueError(msg)
        if offset < _OFFSET_MIN:
            msg = f"offset must be >= {_OFFSET_MIN}; got {offset!r}"
            raise ValueError(msg)
        if not (_WEIRDNESS_MIN <= min_weirdness <= _WEIRDNESS_MAX):
            msg = f"min_weirdness must be between {_WEIRDNESS_MIN} and {_WEIRDNESS_MAX}; got {min_weirdness!r}"
            raise ValueError(msg)
        if since_days is not None and not (_SINCE_DAYS_MIN <= since_days <= _SINCE_DAYS_MAX):
            msg = f"since_days must be between {_SINCE_DAYS_MIN} and {_SINCE_DAYS_MAX}; got {since_days!r}"
            raise ValueError(msg)
