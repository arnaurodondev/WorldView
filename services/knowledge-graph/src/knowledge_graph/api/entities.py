"""Entity-specific query endpoints.

  GET /api/v1/entities/{entity_id}/contradictions
  POST /api/v1/entities/similar

Read-only endpoints.  Uses the read-replica session (R27).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import EntityContradictionsRepoDep, FindSimilarEntitiesReposDep
from knowledge_graph.api.schemas import (
    ContradictionDetailResponse,
    ContradictionSideResponse,
    ContradictionsListResponse,
    SimilarEntitiesRequest,
    SimilarEntitiesResponse,
    SimilarEntityResultItem,
)
from knowledge_graph.application.use_cases.contradiction_lookup import (
    EntityContradictionsUseCase,
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
    claim_repo: EntityContradictionsRepoDep,
    claim_type: str | None = Query(default=None),
    top_k: int = Query(default=20, ge=1, le=100),
) -> ContradictionsListResponse:
    """Return active contradiction links where *entity_id* is the subject.

    Returns an empty ``contradictions`` list when no contradictions exist —
    this is NOT a 404.
    """
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


@router.post("/entities/similar", response_model=SimilarEntitiesResponse)
async def find_similar_entities(
    body: SimilarEntitiesRequest,
    repos: FindSimilarEntitiesReposDep,
) -> SimilarEntitiesResponse:
    """Return top-K similar financial instrument entities by embedding ANN.

    - 404 if ``entity_id`` does not exist.
    - 422 if the entity has no ``fundamentals_ohlcv`` embedding (e.g. non-financial entity).
    - 503 if pgvector ANN is unavailable.

    Uses the read-replica session (R27).
    """
    from knowledge_graph.application.use_cases.find_similar_entities import FindSimilarEntitiesUseCase
    from knowledge_graph.domain.errors import EmbeddingNotAvailableError, EntityNotFoundError

    try:
        entity_dict, results = await FindSimilarEntitiesUseCase().execute(
            entity_repo=repos.entity_repo,  # type: ignore[arg-type]
            embedding_repo=repos.embedding_repo,
            relation_repo=repos.relation_repo,  # type: ignore[arg-type]
            entity_id=body.entity_id,
            top_k=body.top_k,
            min_score=body.min_score,
            include_competitors_only=body.include_competitors_only,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Entity not found") from exc
    except EmbeddingNotAvailableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.exception("pgvector ANN error in find_similar_entities")
        raise HTTPException(status_code=503, detail="Similarity search unavailable") from exc

    return SimilarEntitiesResponse(
        entity_id=body.entity_id,
        canonical_name=str(entity_dict.get("canonical_name", "")),
        results=[
            SimilarEntityResultItem(
                entity_id=r.entity_id,
                canonical_name=r.canonical_name,
                entity_type=r.entity_type,
                ticker=r.ticker,
                exchange=r.exchange,
                ann_similarity_score=r.ann_similarity_score,
                competes_with_confidence=r.competes_with_confidence,
                final_score=r.final_score,
                has_competes_with_relation=r.has_competes_with_relation,
            )
            for r in results
        ],
        total=len(results),
    )
