"""REST API endpoints for the NLP Pipeline service (PRD §6.2.3).

6 endpoints:
  GET  /signals                 — paginated signal list
  GET  /entities                — entity search by text
  POST /vector-search           — semantic section/chunk search
  GET  /entities/{id}           — entity detail with resolution stats
  GET  /entities/{id}/articles  — articles mentioning this entity
  POST /reprocess/{article_id}  — requeue an article for reprocessing
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from nlp_pipeline.api.dependencies import AdminAuthDep, NewsQueryRepoDep, SignalsQueryRepoDep
from nlp_pipeline.api.routes.news import _to_response as _article_to_response
from nlp_pipeline.api.schemas import (
    EntityDetailResponse,
    EntityListResponse,
    EntitySearchResponse,
    RankedNewsResponse,
    ReprocessResponse,
    SignalListResponse,
    SignalResponse,
    VectorSearchHit,
    VectorSearchRequest,
    VectorSearchResponse,
)
from nlp_pipeline.application.use_cases.signals import (
    GetEntityArticlesUseCase,
    GetEntityDetailUseCase,
    ListSignalsUseCase,
    ReprocessArticleUseCase,
    SearchEntitiesUseCase,
    VectorSearchUseCase,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["nlp"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── GET /signals ───────────────────────────────────────────────────────────────


@router.get("/signals", response_model=SignalListResponse)
async def list_signals(
    repo: SignalsQueryRepoDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    doc_id: UUID | None = Query(default=None),
    min_impact_score: float = Query(default=0.0, ge=0.0, le=1.0),
    order_by: str = Query(default="created_at", pattern="^(created_at|market_impact_score)$"),
) -> SignalListResponse:
    """List high-confidence financial signals (from outbox_events).

    Optional filters:
    - ``min_impact_score``: only return signals where market_impact_score >= threshold
    - ``order_by``: ``created_at`` (default) or ``market_impact_score`` (desc)
    """
    items, total = await ListSignalsUseCase().execute(
        repo,
        limit,
        offset,
        doc_id,
        min_impact_score=min_impact_score,
        order_by=order_by,
    )
    return SignalListResponse(
        items=[
            SignalResponse(
                signal_id=item.signal_id,
                doc_id=item.doc_id,
                entity_id=item.entity_id,
                signal_type=item.signal_type,
                confidence=item.confidence,
                evidence_text=item.evidence_text,
                detected_at=item.detected_at,
                market_impact_score=item.market_impact_score,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── GET /entities ──────────────────────────────────────────────────────────────


@router.get("/entities", response_model=EntityListResponse)
async def search_entities(
    repo: SignalsQueryRepoDep,
    q: str = Query(min_length=1, max_length=256),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EntityListResponse:
    """Search entities by mention text (case-insensitive substring)."""
    items, total = await SearchEntitiesUseCase().execute(repo, q, limit, offset)
    return EntityListResponse(
        items=[
            EntitySearchResponse(
                entity_id=item.entity_id,
                canonical_name=item.canonical_name,
                entity_type=item.entity_type,
                mention_count=item.mention_count,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── POST /vector-search ────────────────────────────────────────────────────────


@router.post("/vector-search", response_model=VectorSearchResponse)
async def vector_search(
    body: VectorSearchRequest,
    repo: SignalsQueryRepoDep,
) -> VectorSearchResponse:
    """Semantic search over section embeddings using pgvector ANN.

    Returns section snippets ranked by cosine similarity to the query embedding.
    The embedding is computed via the app-scoped embedding client at runtime.
    """
    hits_data = await VectorSearchUseCase().execute(repo, query=body.query, limit=body.limit)
    return VectorSearchResponse(
        query=body.query,
        hits=[
            VectorSearchHit(
                doc_id=hit.doc_id,
                section_id=hit.section_id,
                score=hit.score,
                snippet=hit.snippet,
            )
            for hit in hits_data
        ],
    )


# ── GET /entities/{id} ────────────────────────────────────────────────────────


@router.get("/entities/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(
    entity_id: UUID,
    repo: SignalsQueryRepoDep,
) -> EntityDetailResponse:
    """Retrieve entity detail with resolution counts."""
    data = await GetEntityDetailUseCase().execute(repo, entity_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return EntityDetailResponse(
        entity_id=data.entity_id,
        canonical_name=data.canonical_name,
        entity_type=data.entity_type,
        mention_count=data.mention_count,
        resolved_count=data.resolved_count,
        provisional_count=data.provisional_count,
    )


# ── GET /entities/{id}/articles ───────────────────────────────────────────────


@router.get("/entities/{entity_id}/articles", response_model=RankedNewsResponse)
async def get_entity_articles(
    entity_id: UUID,
    repo: NewsQueryRepoDep,
    start_date: datetime | None = Query(
        default=None,
        description="Include articles published on or after this datetime (ISO 8601). Defaults to 30 days ago.",
    ),
    end_date: datetime | None = Query(
        default=None,
        description="Include articles published on or before this datetime (ISO 8601). Defaults to now.",
    ),
    order_by: str = Query(
        default="display_relevance_score",
        pattern="^(display_relevance_score|published_at)$",
        description="Sort field — always descending.",
    ),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RankedNewsResponse:
    """List articles that mention this entity, ranked by display_relevance_score.

    Returns an empty list (not 404) when the entity has no articles in range.
    Date range defaults to the last 30 days when not specified.
    """
    now = datetime.now(tz=UTC)
    resolved_end = end_date or now
    resolved_start = start_date or (now - timedelta(days=30))

    if resolved_start > resolved_end:
        from fastapi import HTTPException as _HTTPException

        raise _HTTPException(status_code=422, detail="start_date must be before end_date")

    articles_data, total = await GetEntityArticlesUseCase().execute(
        repo=repo,
        entity_id=entity_id,
        start_date=resolved_start,
        end_date=resolved_end,
        order_by=order_by,
        limit=limit,
        offset=offset,
    )
    return RankedNewsResponse(
        articles=[_article_to_response(a) for a in articles_data],
        total=total,
    )


# ── POST /reprocess/{article_id} ──────────────────────────────────────────────


@router.post("/reprocess/{article_id}", response_model=ReprocessResponse)
async def reprocess_article(
    article_id: UUID,
    repo: SignalsQueryRepoDep,
    _auth: AdminAuthDep,
) -> ReprocessResponse:
    """Requeue an article for reprocessing by inserting a synthetic outbox event.

    The event will trigger the outbox dispatcher which republishes to the
    consumer group for re-ingestion.  This is a best-effort admin operation.
    """
    found = await ReprocessArticleUseCase().execute(repo, article_id)
    if not found:
        raise HTTPException(status_code=404, detail="Article not found")
    return ReprocessResponse(
        article_id=article_id,
        status="queued",
        message="Reprocess request enqueued",
    )
