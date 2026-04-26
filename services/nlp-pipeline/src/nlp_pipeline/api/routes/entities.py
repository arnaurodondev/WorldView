"""Entity endpoints for the NLP Pipeline API.

Endpoints:
  POST /api/v1/entities/resolve          — entity resolution for RAG pipeline (Wave B-2)
  GET  /api/v1/entities/{entity_id}/articles — articles mentioning an entity (rag-chat feed)

Internal endpoints; protected app-wide by InternalJWTMiddleware (no per-route auth needed).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from nlp_pipeline.api.dependencies import EntityMentionRepoDep, EntityResolverDep
from nlp_pipeline.api.schemas import (
    EntityArticleItem,
    EntityArticlesResponse,
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


@router.get("/entities/{entity_id}/briefing-articles", response_model=EntityArticlesResponse)
async def get_entity_articles_feed(
    entity_id: UUID,
    repo: EntityMentionRepoDep,
    limit: int = Query(default=10, ge=1, le=50, description="Max articles to return (1-50)."),
) -> EntityArticlesResponse:
    """Return articles mentioning *entity_id*, newest-first (internal briefing feed).

    Called by rag-chat's BriefingContextGatherer._fetch_entity_articles() to
    gather recent news for an instrument briefing.  Returns an empty list (not 404)
    when the entity has no articles.

    Path is /briefing-articles (not /articles) to avoid shadowing the signals
    router's GET /entities/{entity_id}/articles which applies a watchlist
    ownership guard unsuitable for the rag-chat briefing use case.

    Response shape matches what rag-chat's _map_news_articles() expects:
    ``{"articles": [...], "entity_id": "...", "total": N}``.
    """
    rows = await repo.get_articles_for_entity(entity_id=entity_id, limit=limit)
    entity_id_str = str(entity_id)
    articles = [
        EntityArticleItem(
            article_id=str(row["doc_id"]),
            title=row["title"] or "",
            url=row["url"] or "",
            published_at=row["published_at"],
            source_name=row["source_name"] or "",
            source_type=row["source_type"],
            display_relevance_score=row["display_relevance_score"],
            # entity_id is fixed by the path param; no per-article primary entity
            primary_entity_id=entity_id_str,
        )
        for row in rows
    ]
    _log.debug(  # type: ignore[no-any-return]
        "entity_articles_feed",
        entity_id=entity_id_str,
        count=len(articles),
    )
    return EntityArticlesResponse(
        articles=articles,
        entity_id=entity_id_str,
        total=len(articles),
    )
