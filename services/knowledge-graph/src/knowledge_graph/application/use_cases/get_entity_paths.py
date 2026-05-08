"""GetEntityPathsUseCase — return pre-computed path insights for an entity (PLAN-0074 Wave E2).

R25 compliance: the router injects this use case via a Depends() factory defined in
``knowledge_graph.api.dependencies`` — the router never imports from infrastructure.
R27 compliance: read-only query — the caller must pass a repo bound to the READ session.

The use case also orchestrates lazy LLM explanation generation:
  - For each path whose ``llm_explanation`` is None, a background task is fired via
    ``asyncio.create_task()`` so the hot path is never blocked (NFR-2).
  - ``explanation_pending = True`` is set in the response for those paths.
  - Callers poll the same endpoint after a delay to retrieve the completed explanation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from knowledge_graph.api.schemas.paths import EntityPathsResponse
    from knowledge_graph.application.ports.path_insight_repository import PathInsightRepositoryPort
    from knowledge_graph.application.services.path_explanation_service import PathExplanationService

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Hard limits for query parameter validation (enforced before the DB call).
_LIMIT_MIN = 1
_LIMIT_MAX = 50
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0
_HOPS_MIN = 2
_HOPS_MAX = 5


class GetEntityPathsUseCase:
    """Return the top-N pre-computed path insights for a given anchor entity.

    Args:
        path_insight_repo: Repository bound to a **read-only** session (R27).
        explanation_service: Optional ``PathExplanationService`` used to fire
            background explanation tasks for paths whose ``llm_explanation``
            is still None.  When None, no background task is fired (useful in
            tests or environments without LLM access).
        entity_exists_fn: Optional async callable ``(UUID) -> bool`` that checks
            whether a canonical entity exists.  Used by the router to return 404
            when the entity is not found.  When None, ``entity_exists`` always
            returns True (caller must check externally).

    """

    def __init__(
        self,
        path_insight_repo: PathInsightRepositoryPort,
        explanation_service: PathExplanationService | None = None,
        entity_exists_fn: object | None = None,
    ) -> None:
        self._repo = path_insight_repo
        self._explanation_service = explanation_service
        self._entity_exists_fn = entity_exists_fn

    async def entity_exists(self, entity_id: UUID) -> bool:
        """Check if a canonical entity exists in the DB.

        Returns True when ``entity_exists_fn`` is not configured (trusts caller).
        """
        if self._entity_exists_fn is None:
            return True
        return bool(await self._entity_exists_fn(entity_id))  # type: ignore[call-arg,operator]

    async def execute(
        self,
        entity_id: UUID,
        *,
        limit: int = 10,
        min_score: float = 0.3,
        min_hops: int = 2,
        max_hops: int = 5,
    ) -> EntityPathsResponse:
        """Fetch and return path insights for ``entity_id``.

        Validates query parameters before issuing any DB call.  Raises
        ``ValueError`` for invalid combinations — FastAPI converts these to 422.

        For each path with a missing ``llm_explanation`` an
        ``asyncio.create_task()`` is scheduled against the bound
        ``PathExplanationService`` — the task is fire-and-forget; the caller
        never awaits it (NFR-2 non-blocking hot path).
        """
        # ── Parameter validation ───────────────────────────────────────────
        self._validate_params(limit, min_score, min_hops, max_hops)

        # ── Fetch paths (READ session — R27) ──────────────────────────────
        paths = await self._repo.list_by_anchor(
            entity_id,
            limit=limit,
            min_score=min_score,
            min_hops=min_hops,
            max_hops=max_hops,
        )

        # ── Build public response objects + fire lazy explanation tasks ───
        # Import here so the module can be imported in tests without the
        # full FastAPI application context.
        from knowledge_graph.api.schemas.paths import (
            EntityPathsResponse,
            PathEdgePublic,
            PathInsightPublic,
            PathNodePublic,
        )

        public_paths: list[PathInsightPublic] = []
        freshness_candidates: list[datetime] = []

        for path in paths:
            # Determine whether a background explanation task should fire.
            needs_explanation = path.llm_explanation is None

            if needs_explanation and self._explanation_service is not None:
                # Fire-and-forget — NEVER await (NFR-2: non-blocking hot path).
                # RUF006: store reference so the task is not garbage-collected before
                # it finishes; we intentionally do not await it.
                _task = asyncio.create_task(  # noqa: RUF006
                    self._explanation_service.generate_explanation(
                        insight_id=path.insight_id,
                        path_nodes=list(path.path_nodes),
                        path_edges=list(path.path_edges),
                    ),
                    # Descriptive name makes the task visible in asyncio.all_tasks().
                    name=f"path_explanation_{path.insight_id}",
                )
                logger.debug(  # type: ignore[no-any-return]
                    "path_explanation_task_fired",
                    insight_id=str(path.insight_id),
                    hop_count=path.hop_count,
                )

            public_paths.append(
                PathInsightPublic(
                    insight_id=path.insight_id,
                    hop_count=path.hop_count,
                    harmonic_score=path.harmonic_score,
                    diversity_score=path.diversity_score,
                    surprise_score=path.surprise_score,
                    template_match=path.template_match,
                    composite_score=path.composite_score,
                    path_nodes=[
                        PathNodePublic(
                            entity_id=node.entity_id,
                            name=node.name,
                            entity_type=node.entity_type,
                        )
                        for node in path.path_nodes
                    ],
                    path_edges=[
                        PathEdgePublic(
                            relation_type=edge.relation_type,
                            confidence=edge.confidence,
                        )
                        for edge in path.path_edges
                    ],
                    llm_explanation=path.llm_explanation,
                    # explanation_pending=True when no explanation yet AND a task fired.
                    # If explanation_service is None no task fires, so pending stays False.
                    explanation_pending=(needs_explanation and self._explanation_service is not None),
                    computed_at=path.computed_at,
                )
            )
            freshness_candidates.append(path.computed_at)

        # freshness_ts = MAX(computed_at) across returned paths; None when empty.
        freshness_ts: datetime | None = max(freshness_candidates) if freshness_candidates else None

        return EntityPathsResponse(
            entity_id=entity_id,
            paths=public_paths,
            total=len(public_paths),
            freshness_ts=freshness_ts,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_params(
        limit: int,
        min_score: float,
        min_hops: int,
        max_hops: int,
    ) -> None:
        """Raise ValueError for any invalid parameter combination.

        FastAPI's exception handlers convert ValueError to HTTP 422 so routers
        simply let validation errors propagate unhandled.
        """
        if not (_LIMIT_MIN <= limit <= _LIMIT_MAX):
            msg = f"limit must be between {_LIMIT_MIN} and {_LIMIT_MAX}; got {limit!r}"
            raise ValueError(msg)
        if not (_SCORE_MIN <= min_score <= _SCORE_MAX):
            msg = f"min_score must be between {_SCORE_MIN} and {_SCORE_MAX}; got {min_score!r}"
            raise ValueError(msg)
        if not (_HOPS_MIN <= min_hops <= _HOPS_MAX):
            msg = f"min_hops must be between {_HOPS_MIN} and {_HOPS_MAX}; got {min_hops!r}"
            raise ValueError(msg)
        if not (_HOPS_MIN <= max_hops <= _HOPS_MAX):
            msg = f"max_hops must be between {_HOPS_MIN} and {_HOPS_MAX}; got {max_hops!r}"
            raise ValueError(msg)
        if min_hops > max_hops:
            msg = f"min_hops ({min_hops}) must be <= max_hops ({max_hops})"
            raise ValueError(msg)
