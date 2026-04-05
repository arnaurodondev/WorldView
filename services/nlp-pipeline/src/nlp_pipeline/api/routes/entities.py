"""Entity resolution endpoint — POST /api/v1/entities/resolve (PLAN-0015-B Wave B-2).

Internal endpoint for S8 RAG pipeline to resolve entity names in query text
without requiring a round-trip through the full article consumer pipeline.
No user authentication is required (internal service-to-service call).
"""

from __future__ import annotations

from fastapi import APIRouter

from nlp_pipeline.api.dependencies import EntityResolverDep
from nlp_pipeline.api.schemas import (
    EntityResolveRequest,
    EntityResolveResponse,
    ResolvedEntityResponse,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["entities"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.post("/entities/resolve", response_model=EntityResolveResponse)
async def resolve_entities(
    body: EntityResolveRequest,
    resolver: EntityResolverDep,
) -> EntityResolveResponse:
    """Resolve entity mentions in query text using a 5-stage cascade.

    Returns the highest-confidence match per unique entity, filtered by
    ``min_confidence``. Results are cached in Valkey (TTL 600 s).
    """
    results, normalized = await resolver.execute(
        query_text=body.query_text,
        top_k_per_mention=body.top_k_per_mention,
        min_confidence=body.min_confidence,
    )
    _log.info(  # type: ignore[no-any-return]
        "entity_resolve_request",
        query_len=len(body.query_text),
        result_count=len(results),
    )
    return EntityResolveResponse(
        entities=[
            ResolvedEntityResponse(
                entity_id=r.entity_id,
                canonical_name=r.canonical_name,
                entity_type=r.entity_type,
                confidence=r.confidence,
                ticker=r.ticker,
                isin=r.isin,
                matched_text=r.matched_text,
                resolution_stage=r.resolution_stage,
            )
            for r in results
        ],
        query_text_normalized=normalized,
    )
