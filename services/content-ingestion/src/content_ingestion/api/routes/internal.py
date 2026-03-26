"""Internal API endpoints — service-to-service (S9 webhook → S4)."""

import hashlib

from fastapi import APIRouter, HTTPException, Request, status

import common.ids
import common.time as ct
from content_ingestion.api.dependencies import DbSessionDep, InternalAuthDep
from content_ingestion.api.schemas import IngestSubmitRequest, IngestSubmitResponse
from content_ingestion.domain.entities import SourceType
from content_ingestion.infrastructure.db.repositories.fetch_log import FetchLogRepository
from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.get("/health")
async def internal_health() -> dict[str, str]:
    """Health check for internal service readiness verification (no auth)."""
    return {"status": "healthy"}


@router.post("/ingest/submit", response_model=IngestSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_submit(
    body: IngestSubmitRequest,
    _auth: InternalAuthDep,
    session: DbSessionDep,
    request: Request,
) -> IngestSubmitResponse:
    """Accept a raw document submission from S9 (webhook or manual).

    Exactly one of ``url`` or ``raw_content`` must be provided.
    """
    # Validate: exactly one of url or raw_content
    if body.url and body.raw_content:
        raise HTTPException(status_code=422, detail="Provide exactly one of 'url' or 'raw_content', not both")
    if not body.url and not body.raw_content:
        raise HTTPException(status_code=422, detail="Provide exactly one of 'url' or 'raw_content'")

    # Determine content
    if body.raw_content:
        raw_bytes = body.raw_content.encode("utf-8")
        url = body.url or f"manual://{common.ids.new_ulid()}"
    else:
        # For URL-based submissions, store the URL as a placeholder
        # (actual fetching could be done by the adapter later)
        raw_bytes = (body.url or "").encode("utf-8")
        url = body.url or ""

    url_hash_val = hashlib.sha256(url.encode("utf-8")).hexdigest()
    doc_id = common.ids.new_uuid7()
    now = ct.utc_now()

    # Validate source_type
    try:
        source_type = SourceType(body.source_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid source_type: {body.source_type}")  # noqa: B904

    # Write to MinIO bronze
    storage = request.app.state.storage
    bronze = MinioBronzeAdapter(storage)
    minio_key = await bronze.put_object(
        source_type=str(source_type),
        url_hash=url_hash_val,
        raw_bytes=raw_bytes,
        url=url,
        fetched_at=ct.to_iso8601(now),
        published_at=ct.to_iso8601(body.published_at) if body.published_at else None,
    )

    # Insert fetch_log + outbox atomically
    fetch_log_repo = FetchLogRepository(session)
    outbox_repo = OutboxRepository(session)

    # Dedup check
    if await fetch_log_repo.exists_by_url_hash(url_hash_val):
        return IngestSubmitResponse(doc_id=doc_id, status="duplicate")

    await fetch_log_repo.create(
        url=url,
        url_hash=url_hash_val,
        source_id=doc_id,  # Use doc_id as source reference for manual submissions
        http_status=200,
        byte_size=len(raw_bytes),
        fetched_at=now,
        published_at=body.published_at,
    )

    await outbox_repo.append(
        aggregate_type="article",
        aggregate_id=doc_id,
        event_type="content.article.raw.v1",
        topic="content.article.raw.v1",
        payload={
            "doc_id": str(doc_id),
            "source_type": str(source_type),
            "url": url,
            "url_hash": url_hash_val,
            "minio_key": minio_key,
            "fetched_at": ct.to_iso8601(now),
            "byte_size": len(raw_bytes),
            "published_at": ct.to_iso8601(body.published_at) if body.published_at else None,
            "is_backfill": False,
        },
    )

    await session.commit()
    return IngestSubmitResponse(doc_id=doc_id)
