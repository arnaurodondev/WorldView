"""Weird-connections API — GET /api/v1/connections/weird (PLAN-0112 W5, T-5-02).

A graph-wide feed of the most surprising precomputed connections, read from
``path_insights`` (PRD-0112 FR-7, §6.2).

R25 compliance: this router imports ONLY from the application layer + schema
modules.  All infrastructure wiring lives in ``knowledge_graph.api.dependencies``.
R27 compliance: read-only endpoint — the injected use case is bound to the
read-replica session (pure ``path_insights`` SELECT, no AGE ``LOAD 'age'``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import (  # type: ignore[attr-defined]
    GlobalWeirdConnectionsUseCaseDep,
)
from knowledge_graph.api.schemas.paths import WeirdConnectionsResponse
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["connections"])

_log = get_logger(__name__)  # type: ignore[no-any-return]

# Allowed canonical entity types for the ``entity_type`` filter.  Kept as a
# permissive str query param (the repo treats an unknown value as "no match" →
# empty feed) but validated against this set so callers get a clean 422 for a
# clearly invalid type rather than a silently-empty page.
_ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "company",
        "financial_instrument",
        "person",
        "sector",
        "industry",
        "country",
        "organization",
        "product",
        "event",
        "concept",
    }
)


@router.get(
    "/connections/weird",
    response_model=WeirdConnectionsResponse,
    summary="Global feed of the most surprising connections in the graph (PLAN-0112 W5)",
    description=(
        "Returns the globally most-weird precomputed connections (PRD-0112 FR-7), "
        "read from ``path_insights`` and ranked by ``weirdness`` descending.\n\n"
        "Deduplicated to distinct (src, dst) endpoint pairs — the single "
        "highest-weirdness path is kept per pair.\n\n"
        "**Filters**: ``min_weirdness`` threshold, ``since_days`` (only paths with "
        "a recent edge), ``entity_type`` (paths whose endpoint matches a type).\n\n"
        "**422**: invalid query parameters."
    ),
)
async def get_weird_connections(
    uc: GlobalWeirdConnectionsUseCaseDep,
    limit: int = Query(default=20, ge=1, le=100, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    min_weirdness: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum weirdness threshold."),
    since_days: int | None = Query(
        default=None,
        ge=1,
        le=365,
        description="Only paths with a recent edge (recent-edge proxy: novelty > 0).",
    ),
    entity_type: str | None = Query(
        default=None,
        description="Filter to paths whose src or dst endpoint matches this canonical entity type.",
    ),
) -> WeirdConnectionsResponse:
    """Return the ranked, deduped global weird-connections feed.

    - **200**: ranked feed (``connections`` may be empty when nothing matches).
    - **422**: invalid query parameters (e.g. unknown ``entity_type``).
    """
    # Validate entity_type against the known enum for a clean 422.  FastAPI's
    # Query() already bounds the numeric params; this catches the one free-text
    # param so a typo does not silently return an empty feed.
    if entity_type is not None and entity_type not in _ALLOWED_ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"entity_type must be one of {sorted(_ALLOWED_ENTITY_TYPES)}; got {entity_type!r}",
        )

    try:
        return await uc.execute(  # type: ignore[no-any-return]
            limit=limit,
            offset=offset,
            min_weirdness=min_weirdness,
            since_days=since_days,
            entity_type=entity_type,
        )
    except ValueError as exc:
        # Use-case parameter validation raises ValueError → 422.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
