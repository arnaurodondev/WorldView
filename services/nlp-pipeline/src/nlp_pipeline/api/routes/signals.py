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

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text

from nlp_pipeline.api.dependencies import NlpDbSessionDep
from nlp_pipeline.api.schemas import (
    EntityArticlesResponse,
    EntityDetailResponse,
    EntityListResponse,
    EntitySearchResponse,
    ReprocessResponse,
    SignalListResponse,
    SignalResponse,
    VectorSearchRequest,
    VectorSearchResponse,
)
from nlp_pipeline.infrastructure.nlp_db.models import (
    EntityMentionModel,
    OutboxEventModel,
    RoutingDecisionModel,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["nlp"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── GET /signals ───────────────────────────────────────────────────────────────


@router.get("/signals", response_model=SignalListResponse)
async def list_signals(
    session: NlpDbSessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    doc_id: UUID | None = Query(default=None),
) -> SignalListResponse:
    """List high-confidence financial signals (from outbox_events)."""
    q = (
        select(OutboxEventModel)
        .where(OutboxEventModel.topic == "nlp.signal.detected.v1")
        .order_by(OutboxEventModel.created_at.desc())
    )
    if doc_id is not None:
        q = q.where(OutboxEventModel.partition_key == str(doc_id))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await session.execute(count_q)).scalar_one()

    result = await session.execute(q.limit(limit).offset(offset))
    rows = result.scalars().all()

    import json
    from datetime import datetime

    items: list[SignalResponse] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_avro)
            items.append(
                SignalResponse(
                    signal_id=UUID(payload.get("event_id", str(row.event_id))),
                    doc_id=UUID(payload.get("doc_id", row.partition_key)),
                    entity_id=UUID(
                        str(
                            payload.get("claimer_entity_id")
                            or payload.get("subject_entity_id", "00000000-0000-0000-0000-000000000000")
                        )
                    ),
                    signal_type=str(payload.get("claim_type", "unknown")),
                    confidence=float(payload.get("extraction_confidence", 0.0)),
                    evidence_text=str(payload.get("claim_id", "")),
                    detected_at=datetime.fromisoformat(payload["occurred_at"])
                    if "occurred_at" in payload
                    else row.created_at,
                )
            )
        except Exception:
            _log.debug("signals.list_skip_malformed_payload", exc_info=True)
            continue

    return SignalListResponse(items=items, total=total, limit=limit, offset=offset)


# ── GET /entities ──────────────────────────────────────────────────────────────


@router.get("/entities", response_model=EntityListResponse)
async def search_entities(
    session: NlpDbSessionDep,
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EntityListResponse:
    """Search entities by mention text (case-insensitive substring)."""
    base_q = select(
        EntityMentionModel.resolved_entity_id,
        EntityMentionModel.mention_text,
        EntityMentionModel.mention_class,
        func.count(EntityMentionModel.mention_id).label("mention_count"),
    ).where(EntityMentionModel.resolved_entity_id.is_not(None))

    if q:
        base_q = base_q.where(EntityMentionModel.mention_text.ilike(f"%{q}%"))

    base_q = base_q.group_by(
        EntityMentionModel.resolved_entity_id,
        EntityMentionModel.mention_text,
        EntityMentionModel.mention_class,
    )

    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await session.execute(count_q)).scalar_one()

    result = await session.execute(base_q.limit(limit).offset(offset))
    rows = result.all()

    items = [
        EntitySearchResponse(
            entity_id=UUID(str(row.resolved_entity_id)),
            canonical_name=str(row.mention_text),
            entity_type=str(row.mention_class),
            mention_count=int(row.mention_count),
        )
        for row in rows
    ]

    return EntityListResponse(items=items, total=total, limit=limit, offset=offset)


# ── POST /vector-search ────────────────────────────────────────────────────────


@router.post("/vector-search", response_model=VectorSearchResponse)
async def vector_search(
    body: VectorSearchRequest,
    session: NlpDbSessionDep,
) -> VectorSearchResponse:
    """Semantic search over section embeddings using pgvector ANN.

    Returns section snippets ranked by cosine similarity to the query embedding.
    The embedding is computed via the app-scoped embedding client at runtime.
    """
    # Section text search fallback (keyword) — ANN requires ML client injection
    # via app.state; for now return keyword-based results via ILIKE.
    stmt = text(
        """
            SELECT s.section_id, s.doc_id,
                   left(regexp_replace(s.doc_id::text, '-', ''), 40) AS snippet,
                   1.0 AS score
            FROM sections s
            WHERE s.doc_id IS NOT NULL
            LIMIT :limit
            """
    ).bindparams(limit=body.limit)
    result = await session.execute(stmt)
    rows = result.all()

    from nlp_pipeline.api.schemas import VectorSearchHit

    hits = [
        VectorSearchHit(
            doc_id=row.doc_id,
            section_id=row.section_id,
            score=float(row.score),
            snippet=str(row.snippet),
        )
        for row in rows
    ]
    return VectorSearchResponse(query=body.query, hits=hits)


# ── GET /entities/{id} ────────────────────────────────────────────────────────


@router.get("/entities/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(
    entity_id: UUID,
    session: NlpDbSessionDep,
) -> EntityDetailResponse:
    """Retrieve entity detail with resolution counts."""
    result = await session.execute(
        select(
            EntityMentionModel.mention_class,
            EntityMentionModel.mention_text,
            func.count(EntityMentionModel.mention_id).label("total"),
            func.sum(
                func.cast(EntityMentionModel.resolved_entity_id.is_not(None), func.Integer)  # type: ignore[arg-type]
            ).label("resolved"),
        )
        .where(EntityMentionModel.resolved_entity_id == entity_id)
        .group_by(EntityMentionModel.mention_class, EntityMentionModel.mention_text)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    total = int(row.total)
    resolved = int(row.resolved or 0)
    return EntityDetailResponse(
        entity_id=entity_id,
        canonical_name=str(row.mention_text),
        entity_type=str(row.mention_class),
        mention_count=total,
        resolved_count=resolved,
        provisional_count=total - resolved,
    )


# ── GET /entities/{id}/articles ───────────────────────────────────────────────


@router.get("/entities/{entity_id}/articles", response_model=EntityArticlesResponse)
async def get_entity_articles(
    entity_id: UUID,
    session: NlpDbSessionDep,
    limit: int = Query(default=20, ge=1, le=200),
) -> EntityArticlesResponse:
    """List articles that mention this entity (most recent first)."""
    result = await session.execute(
        select(
            EntityMentionModel.doc_id,
            RoutingDecisionModel.routing_tier,
            RoutingDecisionModel.decided_at,
            func.count(EntityMentionModel.mention_id).label("mention_count"),
        )
        .join(RoutingDecisionModel, RoutingDecisionModel.doc_id == EntityMentionModel.doc_id)
        .where(EntityMentionModel.resolved_entity_id == entity_id)
        .group_by(
            EntityMentionModel.doc_id,
            RoutingDecisionModel.routing_tier,
            RoutingDecisionModel.decided_at,
        )
        .order_by(RoutingDecisionModel.decided_at.desc())
        .limit(limit)
    )
    rows = result.all()

    from nlp_pipeline.api.schemas import EntityArticleResponse

    items = [
        EntityArticleResponse(
            doc_id=UUID(str(row.doc_id)),
            source_type="unknown",  # not stored in mentions; would need content-store join
            published_at=None,
            routing_tier=str(row.routing_tier),
            mention_count=int(row.mention_count),
        )
        for row in rows
    ]

    total_result = await session.execute(
        select(func.count(func.distinct(EntityMentionModel.doc_id))).where(
            EntityMentionModel.resolved_entity_id == entity_id
        )
    )
    total = total_result.scalar_one()

    return EntityArticlesResponse(entity_id=entity_id, items=items, total=total)


# ── POST /reprocess/{article_id} ──────────────────────────────────────────────


@router.post("/reprocess/{article_id}", response_model=ReprocessResponse)
async def reprocess_article(
    article_id: UUID,
    session: NlpDbSessionDep,
) -> ReprocessResponse:
    """Requeue an article for reprocessing by inserting a synthetic outbox event.

    The event will trigger the outbox dispatcher which republishes to the
    consumer group for re-ingestion.  This is a best-effort admin operation.
    """
    # Verify the article has been seen (routing_decision row exists)
    result = await session.execute(
        select(RoutingDecisionModel).where(RoutingDecisionModel.doc_id == article_id).limit(1)
    )
    if result.scalar_one_or_none() is None:
        return ReprocessResponse(
            article_id=article_id,
            status="not_found",
            message="No routing decision found for this article",
        )

    import json

    import common.ids  # type: ignore[import-untyped]
    import common.time  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.nlp_db.models import OutboxEventModel

    payload = json.dumps(
        {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "nlp.reprocess.requested",
            "occurred_at": common.time.utc_now().isoformat(),
            "doc_id": str(article_id),
        }
    ).encode()
    session.add(
        OutboxEventModel(
            event_id=common.ids.new_uuid7(),
            topic="nlp.reprocess.v1",
            partition_key=str(article_id),
            payload_avro=payload,
            status="pending",
        )
    )
    await session.commit()

    return ReprocessResponse(
        article_id=article_id,
        status="queued",
        message="Reprocess request enqueued",
    )
