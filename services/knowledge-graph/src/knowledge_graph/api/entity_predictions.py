"""Entity-predictions endpoint — GET /api/v1/entities/{entity_id}/predictions (PLAN-0056 Wave C4).

Read-only endpoint backed by GetEntityPredictionsUseCase.  Returns the
prediction markets that reference a given entity, together with the directional
polarity recorded on the exposure (the read side of the KG linkage built in
Waves C2/C2b/C3).

``condition_id`` (Polymarket conditionId) is the critical join key: the S9
gateway (Wave E1) proxies this endpoint and hydrates current odds/liquidity from
S3 by condition_id.

R25 compliance: the route depends only on GetEntityPredictionsUseCaseDep, wired
in dependencies.py — it never imports from the infrastructure layer.
R27 compliance: the use case runs on the read-replica session (ReadOnlyDbSessionDep
inside the Dep factory).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from knowledge_graph.api.dependencies import GetEntityPredictionsUseCaseDep
from knowledge_graph.api.schemas import EntityPredictionItem, EntityPredictionsResponse
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["entity-predictions"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get(
    "/entities/{entity_id}/predictions",
    response_model=EntityPredictionsResponse,
    summary="Prediction markets that reference an entity, with polarity",
)
async def list_entity_predictions(
    entity_id: UUID,
    uc: GetEntityPredictionsUseCaseDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EntityPredictionsResponse:
    """List the prediction markets referencing an entity, with polarity.

    Each item is one Polymarket market whose synthetic entity-linking document
    resolved to this entity (event_type='prediction').  Exposures on non-prediction
    events (corporate/earnings/macro) are excluded by the repository query.

    - 200: list (possibly empty) with total/limit/offset.  An entity with no
      linked prediction markets returns ``{"items": [], "total": 0, ...}`` —
      never a 404 (absence of links is a valid, expected state).
    - 422: invalid entity_id UUID, or limit/offset out of range.

    Results are ordered by market close time (soonest-open first), tie-broken by
    creation time.  ``limit`` is clamped to 1-200 by FastAPI query validation.

    R25: infra wired in dependencies.py via GetEntityPredictionsUseCaseDep.
    R27: read-only (read-replica session inside the Dep factory).
    """
    items, total = await uc.execute(entity_id, limit=limit, offset=offset)

    return EntityPredictionsResponse(
        items=[
            EntityPredictionItem(
                condition_id=str(row["condition_id"]) if row.get("condition_id") else "",
                question=str(row["question"]) if row.get("question") else "",
                polarity=(str(row["polarity"]) if row.get("polarity") else None),
                polarity_confidence=row.get("polarity_confidence"),  # type: ignore[arg-type]
                close_time=row.get("close_time"),  # type: ignore[arg-type]
                confidence=float(row["confidence"]),  # type: ignore[arg-type]
            )
            for row in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
