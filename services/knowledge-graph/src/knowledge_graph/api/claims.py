"""Claims search endpoint — POST /api/v1/claims/search (Wave C-1).

Read-only endpoint backed by ArticleClaimSearchUseCase.
Uses the read-replica session (R27).
"""

from __future__ import annotations

from fastapi import APIRouter

from knowledge_graph.api.dependencies import ClaimRepoDep
from knowledge_graph.api.schemas import (
    ClaimResponse,
    ClaimsSearchRequest,
    ClaimsSearchResponse,
)
from knowledge_graph.application.use_cases.claim_search import ArticleClaimSearchUseCase
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["claims"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.post("/claims/search", response_model=ClaimsSearchResponse)
async def search_claims(
    body: ClaimsSearchRequest,
    claim_repo: ClaimRepoDep,
) -> ClaimsSearchResponse:
    """Search claims for a set of entities with optional filters.

    Returns claims ordered by ``extraction_confidence DESC``.
    At most 10 entity IDs accepted per request.
    """
    results = await ArticleClaimSearchUseCase().execute(
        claim_repo=claim_repo,  # type: ignore[arg-type]
        entity_ids=body.entity_ids,
        claim_types=body.claim_types if body.claim_types else None,
        date_from=body.date_from,
        date_to=body.date_to,
        min_confidence=body.min_confidence,
        top_k=body.top_k,
    )
    return ClaimsSearchResponse(
        claims=[
            ClaimResponse(
                claim_id=r.claim_id,
                subject_entity_id=r.subject_entity_id,
                claim_type=r.claim_type,
                polarity=r.polarity,
                claim_text=r.claim_text,
                extraction_confidence=r.extraction_confidence,
                doc_id=r.doc_id,
                created_at=r.created_at,
            )
            for r in results
        ],
    )
