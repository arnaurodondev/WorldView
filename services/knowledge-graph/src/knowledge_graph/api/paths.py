"""Path Insights API — GET /api/v1/entities/{entity_id}/paths (PLAN-0074 Wave E2).

R25 compliance: this router imports ONLY from the application layer and schema
modules.  All infrastructure wiring lives in ``knowledge_graph.api.dependencies``.
R27 compliance: read-only endpoint — ``GetEntityPathsUseCaseDep`` uses the
read-replica session.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import GetEntityPathsUseCaseDep  # type: ignore[attr-defined]
from knowledge_graph.api.schemas.paths import EntityPathsResponse
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["paths"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get(
    "/entities/{entity_id}/paths",
    response_model=EntityPathsResponse,
    summary="List pre-computed multi-hop opportunity paths for an entity",
    description=(
        "Returns the top-N pre-computed scored path insights originating from "
        "``entity_id``, ordered by ``composite_score`` descending.\n\n"
        "**Lazy LLM explanation**: for paths whose ``llm_explanation`` is ``null``, "
        "a background task is fired to generate the explanation.  ``explanation_pending`` "
        "is set to ``true`` for those paths — poll again after a short delay.\n\n"
        "**404**: returned when the entity does not exist in ``canonical_entities``.\n\n"
        "**Empty list** (``total=0``) is returned when the entity exists but has no "
        "computed paths yet — this is NOT a 404."
    ),
)
async def get_entity_paths(
    entity_id: UUID,
    uc: GetEntityPathsUseCaseDep,
    limit: int = Query(default=10, ge=1, le=50, description="Maximum number of paths to return."),
    min_score: float = Query(default=0.3, ge=0.0, le=1.0, description="Minimum composite_score threshold."),
    min_hops: int = Query(default=2, ge=2, le=5, description="Minimum hop count (inclusive)."),
    max_hops: int = Query(default=5, ge=2, le=5, description="Maximum hop count (inclusive)."),
) -> EntityPathsResponse:
    """Return the top-N multi-hop path insights for *entity_id*.

    - **200**: paths returned (``paths`` list may be empty when none meet the filters).
    - **404**: entity not found in ``canonical_entities``.
    - **422**: invalid query parameters (e.g. ``min_hops > max_hops``).
    """
    # Validate the min_hops <= max_hops constraint that FastAPI ge/le cannot express.
    # The use case also validates this — the check here gives a cleaner 422 detail.
    if min_hops > max_hops:
        raise HTTPException(
            status_code=422,
            detail=f"min_hops ({min_hops}) must be <= max_hops ({max_hops})",
        )

    # ── Entity existence check (R25 compliant) ─────────────────────────────
    # The use case's entity_exists() delegates to an injected callable that is
    # wired in dependencies.py — the router never imports from infrastructure.
    if not await uc.entity_exists(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        response = await uc.execute(
            entity_id,
            limit=limit,
            min_score=min_score,
            min_hops=min_hops,
            max_hops=max_hops,
        )
    except ValueError as exc:
        # Use-case parameter validation raises ValueError → 422.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return response  # type: ignore[no-any-return]
