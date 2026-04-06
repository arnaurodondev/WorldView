"""Entity-specific query endpoints (Wave C-1).

  GET /api/v1/entities/{entity_id}/contradictions

Read-only endpoints backed by EntityContradictionsUseCase.
Uses the read-replica session (R27).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.api.schemas import (
    ContradictionDetailResponse,
    ContradictionSideResponse,
    ContradictionsListResponse,
)
from knowledge_graph.application.use_cases.contradiction_lookup import (
    EntityContradictionsUseCase,
)
from knowledge_graph.infrastructure.intelligence_db.repositories.claim_repository import (
    ClaimRepository,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["entities"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get(
    "/entities/{entity_id}/contradictions",
    response_model=ContradictionsListResponse,
)
async def get_entity_contradictions(
    entity_id: UUID,
    session: ReadOnlyDbSessionDep,
    claim_type: str | None = Query(default=None),
    top_k: int = Query(default=20, ge=1, le=100),
) -> ContradictionsListResponse:
    """Return active contradiction links where *entity_id* is the subject.

    Returns an empty ``contradictions`` list when no contradictions exist —
    this is NOT a 404.
    """
    claim_repo = ClaimRepository(session)
    contradictions = await EntityContradictionsUseCase().execute(
        claim_repo=claim_repo,  # type: ignore[arg-type]
        entity_id=entity_id,
        claim_type=claim_type,
        top_k=top_k,
    )
    return ContradictionsListResponse(
        entity_id=entity_id,
        contradictions=[
            ContradictionDetailResponse(
                claim_type=c.claim_type,
                strength=c.strength,
                detected_at=c.detected_at,
                sides=[
                    ContradictionSideResponse(
                        polarity=s.polarity,
                        confidence=s.confidence,
                        doc_id=s.doc_id,
                        claim_text=s.claim_text,
                        evidence_date=s.evidence_date,
                    )
                    for s in c.sides
                ],
            )
            for c in contradictions
        ],
    )
