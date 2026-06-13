"""Path Insights API — GET /api/v1/entities/{entity_id}/paths (PLAN-0074 Wave E2).

R25 compliance: this router imports ONLY from the application layer and schema
modules.  All infrastructure wiring lives in ``knowledge_graph.api.dependencies``.
R27 compliance: read-only endpoint — ``GetEntityPathsUseCaseDep`` uses the
read-replica session.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import (  # type: ignore[attr-defined]
    FindPathsBetweenUseCaseDep,
    GetEntityPathsUseCaseDep,
)
from knowledge_graph.api.schemas.paths import EntityPathsResponse, PathsBetweenResponse
from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
from knowledge_graph.application.use_cases.find_paths_between import (
    PathsBetweenEntityNotFoundError,
    PathsBetweenSameEntityError,
)
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


@router.get(
    "/paths/between",
    response_model=PathsBetweenResponse,
    summary="On-demand pairwise pathfinding — is A connected to B, and how? (PLAN-0112 W4)",
    description=(
        "Bounded on-demand search for paths between two entities (PRD-0112 FR-8). "
        "Reuses the staged variable-length-edge engine (BP-687) for the existence/"
        "shortest-hop probe and the WeirdnessScorer for ranking.\n\n"
        "**connected=false / shortest_hops=null** when no path exists within "
        "``max_hops``.  Paths are ranked by ``weirdness`` descending, then "
        "``hop_count`` ascending.\n\n"
        "**400**: ``source == target``.  **404**: an endpoint does not exist.  "
        "**422**: ``max_hops`` / ``limit`` out of range.  **503**: AGE traversal "
        "exceeded the statement timeout (retry)."
    ),
)
async def get_paths_between(
    uc: FindPathsBetweenUseCaseDep,
    source: UUID = Query(..., description="Source entity UUID."),
    target: UUID = Query(..., description="Target entity UUID (must differ from source)."),
    max_hops: int = Query(default=3, ge=1, le=3, description="Maximum path length (1..path_max_hops)."),
    limit: int = Query(default=5, ge=1, le=20, description="Maximum ranked paths to return."),
    meaningful_only: bool = Query(
        default=False,
        description="When true, prune membership edges from the traversal results.",
    ),
) -> PathsBetweenResponse:
    """Return ranked pairwise paths between *source* and *target*.

    - **200**: response with ``connected`` flag + ranked ``paths`` (empty when
      disconnected within ``max_hops``).
    - **400**: ``source == target``.
    - **404**: ``source`` or ``target`` not found in ``canonical_entities``.
    - **422**: ``max_hops`` or ``limit`` out of range (FastAPI ge/le + use case).
    - **503**: AGE traversal timed out — transient, retry.
    """
    try:
        return await uc.execute(  # type: ignore[no-any-return]
            source,
            target,
            max_hops=max_hops,
            limit=limit,
            meaningful_only=meaningful_only,
        )
    except PathsBetweenSameEntityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PathsBetweenEntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Entity not found") from exc
    except ValueError as exc:
        # Use-case bound validation raises ValueError → 422.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CypherTimeoutError as exc:
        # AGE statement timeout → 503 with retry hint (PRD §6.2).
        raise HTTPException(
            status_code=503,
            detail="Path search timed out; please retry.",
            headers={"Retry-After": "5"},
        ) from exc
