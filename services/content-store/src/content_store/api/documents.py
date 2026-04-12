"""Batch document metadata endpoint — internal use by S8 RAG/Chat."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from content_store.api.dependencies import BatchDocumentsUseCaseDep
from content_store.api.schemas import (
    BatchDocumentsRequest,
    BatchDocumentsResponse,
    DocumentMetadataResponse,
)
from content_store.domain.errors import DomainError

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post("/documents/batch", response_model=BatchDocumentsResponse)
async def batch_documents(
    body: BatchDocumentsRequest,
    use_case: BatchDocumentsUseCaseDep,
) -> BatchDocumentsResponse:
    """Fetch metadata for up to 50 documents by doc_id.

    Internal endpoint — protected by InternalJWTMiddleware (PRD-0025, RS256).
    Missing doc_ids are silently omitted from the response.

    Errors:
    - 401: missing or invalid X-Internal-JWT
    - 400: more than 50 doc_ids requested
    - 422: malformed request (invalid UUID, empty list)
    """
    try:
        metadata_list = await use_case.execute(body.doc_ids)
    except DomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchDocumentsResponse(
        documents=[
            DocumentMetadataResponse(
                doc_id=m.doc_id,
                title=m.title,
                url=m.url,
                published_at=m.published_at,
                source_name=m.source_name,
                source_type=m.source_type,
                word_count=m.word_count,
            )
            for m in metadata_list
        ],
    )
