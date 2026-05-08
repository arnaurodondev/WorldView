"""Enhanced chunk search endpoint — POST /api/v1/search/chunks (PLAN-0015-B Wave B-3).

Internal endpoint for S8 RAG pipeline to perform ANN vector search with inline
entity annotations and citation metadata in a single round trip.
No user authentication is required (internal service-to-service call).
"""

from __future__ import annotations

from fastapi import APIRouter

from nlp_pipeline.api.dependencies import ChunkSearchUseCaseDep
from nlp_pipeline.api.schemas import (
    ChunkEntityAnnotationResponse,
    ChunkSearchRequest,
    ChunkSearchResponse,
    EnrichedChunkResultResponse,
    SourceMetadataResponse,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["search"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.post("/search/chunks", response_model=ChunkSearchResponse)
async def search_chunks(
    body: ChunkSearchRequest,
    use_case: ChunkSearchUseCaseDep,
) -> ChunkSearchResponse:
    """ANN search on chunk/section embeddings with entity annotations and source metadata.

    Exactly one of ``query_text`` or ``query_embedding`` must be provided.
    When ``query_text`` is supplied, the service embeds it (cached in Valkey 1h).
    When ``query_embedding`` is supplied (pre-computed by S8), the embed step
    is skipped.
    """
    # PLAN-0063 W5-3: forward the new search_type literal through to the use
    # case, which dispatches between the ANN / lexical / hybrid execution
    # paths. Default is "ann" so the existing API contract is unchanged.
    results, total_searched, embedding_model = await use_case.execute(
        query_text=body.query_text,
        query_embedding=body.query_embedding,
        granularity=body.granularity,
        top_k=body.top_k,
        min_score=body.min_score,
        include_entities=body.include_entities,
        date_from=body.date_from,
        date_to=body.date_to,
        source_types=body.source_types,
        search_type=body.search_type,
        # PLAN-0078 Wave C: entity filter params from the Pydantic schema.
        entity_ids=body.entity_ids,
        entity_types=body.entity_types,
        # PLAN-0086 Wave C-1: tenant scope filter — prevents data leakage between tenants.
        # body.tenant_id is None by default (public-only); set by internal callers (S8).
        tenant_id=body.tenant_id,
    )

    _log.info(  # type: ignore[no-any-return]
        "chunk_search_request",
        granularity=body.granularity,
        top_k=body.top_k,
        result_count=len(results),
        total_searched=total_searched,
    )

    return ChunkSearchResponse(
        results=[
            EnrichedChunkResultResponse(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                section_id=r.section_id,
                granularity=r.granularity,
                text=r.text,
                score=r.score,
                source_metadata=SourceMetadataResponse(
                    title=r.source_metadata.title,
                    url=r.source_metadata.url,
                    published_at=r.source_metadata.published_at,
                    source_name=r.source_metadata.source_name,
                    source_type=r.source_metadata.source_type,
                ),
                entities=[
                    ChunkEntityAnnotationResponse(
                        entity_id=e.entity_id,
                        canonical_name=e.canonical_name,
                        entity_type=e.entity_type,
                        confidence=e.confidence,
                    )
                    for e in r.entities
                ],
                section_type=r.section_type,
                heading_path=r.heading_path,
            )
            for r in results
        ],
        total_searched=total_searched,
        embedding_model=embedding_model,
    )
