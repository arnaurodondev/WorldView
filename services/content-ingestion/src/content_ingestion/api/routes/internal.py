"""Internal API endpoints — service-to-service (S9 webhook → S4)."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, status

import common.ids  # type: ignore[import-untyped]
from content_ingestion.api.dependencies import BronzeStorageDep, InternalAuthDep, UoWDep
from content_ingestion.api.schemas import IngestSubmitRequest, IngestSubmitResponse, check_url_ssrf_async
from content_ingestion.application.use_cases.submit_content import SubmitContentUseCase
from content_ingestion.domain.entities import SourceType

router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.get("/health")
async def internal_health() -> dict[str, str]:
    """Health check for internal service readiness verification (no auth)."""
    return {"status": "healthy"}


@router.post("/ingest/submit", response_model=IngestSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_submit(
    body: IngestSubmitRequest,
    _auth: InternalAuthDep,
    uow: UoWDep,
    bronze: BronzeStorageDep,
) -> IngestSubmitResponse:
    """Accept a raw document submission from S9 (webhook or manual).

    Exactly one of ``url`` or ``raw_content`` must be provided.
    """
    # Validate: exactly one of url or raw_content
    if body.url and body.raw_content:
        raise HTTPException(status_code=422, detail="Provide exactly one of 'url' or 'raw_content', not both")
    if not body.url and not body.raw_content:
        raise HTTPException(status_code=422, detail="Provide exactly one of 'url' or 'raw_content'")

    # Async SSRF check — DNS resolution with timeout (BP-022, BP-023)
    if body.url:
        try:
            await check_url_ssrf_async(body.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Determine content
    if body.raw_content:
        raw_bytes = body.raw_content.encode("utf-8")
        url = body.url or f"manual://{common.ids.new_ulid()}"
    else:
        raw_bytes = (body.url or "").encode("utf-8")
        url = body.url or ""

    url_hash_val = hashlib.sha256(url.encode("utf-8")).hexdigest()

    # Validate source_type
    try:
        source_type = SourceType(body.source_type)
    except ValueError:
        raise HTTPException(  # noqa: B904
            status_code=400,
            detail="Invalid source_type. Allowed: eodhd, sec_edgar, finnhub, newsapi, manual",
        )

    uc = SubmitContentUseCase(uow, bronze)
    result = await uc.execute(
        url=url,
        url_hash=url_hash_val,
        raw_bytes=raw_bytes,
        source_type=str(source_type),
        published_at=body.published_at,
    )
    return IngestSubmitResponse(doc_id=result.doc_id, status=result.status)
