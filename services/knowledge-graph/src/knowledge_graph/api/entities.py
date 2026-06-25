"""Entity-specific query endpoints.

  GET /api/v1/entities/{entity_id}
  GET /api/v1/entities/{entity_id}/contradictions
  GET /api/v1/entities/{entity_id}/intelligence
  GET /internal/v1/entities/{entity_id}/intelligence  (S8 → S7 service-to-service)
  POST /api/v1/entities/similar

Read-only endpoints.  Uses the read-replica session (R27).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from knowledge_graph.api.dependencies import (
    EntityContradictionsRepoDep,
    FindSimilarEntitiesReposDep,
    GetEntityDetailUseCaseDep,
    GetEntityIntelligenceUseCaseDep,
)
from knowledge_graph.api.schemas import (
    ContradictionDetailResponse,
    ContradictionSideResponse,
    ContradictionsListResponse,
    EntityPublic,
    SimilarEntitiesRequest,
    SimilarEntitiesResponse,
    SimilarEntityResultItem,
)
from knowledge_graph.api.schemas_intelligence import EntityIntelligencePublic
from knowledge_graph.application.use_cases.contradiction_lookup import (
    EntityContradictionsUseCase,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["entities"])

_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get(
    "/entities/{entity_id}",
    response_model=EntityPublic,
    summary="Get canonical entity detail with enrichment",
)
async def get_entity_detail(
    entity_id: UUID,
    uc: GetEntityDetailUseCaseDep,
) -> EntityPublic:
    """Return the canonical entity with enrichment fields (description, metadata, completeness).

    PLAN-0099 (node-click panel): also returns ``health_score``, active
    ``aliases``, the ``top_relations`` (ranked by summary_authority) and the
    total ``relation_count``.  Recent article/mention counts are NOT here —
    they live in nlp_db (S6) and are exposed via the gateway's
    GET /v1/entities/{id}/articles (R9: no cross-service DB access).

    - 200: entity found (enrichment fields may be null if not yet enriched)
    - 404: entity does not exist
    """
    result = await uc.execute(entity_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    from knowledge_graph.api.schemas import EntityAliasPublic, EntityMetadata, EntityRelationBrief

    entity = result.entity
    return EntityPublic(
        entity_id=entity.entity_id,
        canonical_name=entity.canonical_name,
        entity_type=entity.entity_type,
        ticker=entity.ticker,
        isin=entity.isin,
        exchange=entity.exchange,
        description=entity.description,
        data_completeness=entity.data_completeness,
        enriched_at=entity.enriched_at,
        metadata=EntityMetadata.model_validate(entity.metadata),
        health_score=entity.health_score,
        aliases=[
            EntityAliasPublic(
                alias_text=str(a["alias_text"]),
                alias_type=str(a["alias_type"]),
            )
            for a in result.aliases
        ],
        top_relations=[
            EntityRelationBrief(
                relation_id=r["relation_id"],
                canonical_type=str(r["canonical_type"]),
                direction=str(r.get("direction") or "outbound"),
                other_entity_id=r["other_entity_id"],
                other_entity_name=r.get("other_entity_name"),
                other_entity_type=r.get("other_entity_type"),
                confidence=r.get("confidence"),
                evidence_count=int(r.get("evidence_count") or 0),
                relation_summary=r.get("relation_summary"),
            )
            for r in result.top_relations
        ],
        relation_count=result.relation_count,
    )


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


# ── Entity intelligence (PRD-0074 Wave D) ─────────────────────────────────────


async def _get_intelligence(
    entity_id: UUID,
    uc: GetEntityIntelligenceUseCaseDep,
) -> EntityIntelligencePublic:
    """Shared logic for public and internal entity intelligence endpoints."""
    result = await uc.execute(entity_id=entity_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@router.get(
    "/entities/{entity_id}/intelligence",
    response_model=EntityIntelligencePublic,
    summary="Aggregated entity intelligence — narrative, confidence breakdown, metrics",
)
async def get_entity_intelligence(
    entity_id: UUID,
    uc: GetEntityIntelligenceUseCaseDep,
) -> EntityIntelligencePublic:
    """Return aggregated intelligence for a canonical entity.

    Includes:
    - Current narrative (if generated)
    - Confidence breakdown: avg support/corroboration/contradiction, source distribution, 90-day trend
    - key_metrics: entity-type-specific fields from metadata JSONB
    - data_completeness: fraction of expected metadata fields populated

    - 200: intelligence assembled (confidence fields may be null if no evidence yet)
    - 404: entity does not exist
    - 422: invalid UUID format

    Uses ReadOnlyDbSessionDep (R27 — read-only throughout).
    """
    return await _get_intelligence(entity_id, uc)


# ── Internal route (S8 → S7 service-to-service) ───────────────────────────────
# Same logic, dedicated prefix so it can be blocked at the public API gateway.
# Wave G will add the S9 proxy that exposes this to external clients.

_internal_router = APIRouter(prefix="/internal/v1", tags=["internal", "entities"])


@_internal_router.get(
    "/entities/{entity_id}/intelligence",
    response_model=EntityIntelligencePublic,
    summary="[Internal] Entity intelligence for S8 rag-chat consumption",
)
async def get_entity_intelligence_internal(
    entity_id: UUID,
    uc: GetEntityIntelligenceUseCaseDep,
) -> EntityIntelligencePublic:
    """Internal-only route: identical to the public intelligence endpoint.

    Accessed by S8 (rag-chat) to enrich chat responses with entity context.
    Wave G will add the S9 gateway proxy to expose it externally.
    """
    return await _get_intelligence(entity_id, uc)
