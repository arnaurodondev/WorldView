"""Batch document metadata, cluster-size, and cluster-articles endpoints — internal use."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from content_store.api.dependencies import (
    BatchClusterSizesUseCaseDep,
    BatchDocumentsUseCaseDep,
    ClusterArticlesUseCaseDep,
)
from content_store.api.schemas import (
    BatchClusterSizesRequest,
    BatchClusterSizesResponse,
    BatchDocumentsRequest,
    BatchDocumentsResponse,
    ClusterArticleResponse,
    ClusterArticlesResponse,
    ClusterSizeEntry,
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


@router.post("/documents/cluster-sizes", response_model=BatchClusterSizesResponse)
async def batch_cluster_sizes(
    body: BatchClusterSizesRequest,
    use_case: BatchClusterSizesUseCaseDep,
) -> BatchClusterSizesResponse:
    """Return near-duplicate cluster size for up to 100 documents.

    Internal endpoint — protected by InternalJWTMiddleware (PRD-0025, RS256).

    A cluster_size of 1 means the document has no detected near-duplicates.
    A cluster_size of N (N > 1) means this doc + (N-1) near-duplicate siblings.

    WHY this endpoint: allows the API gateway to enrich ranked article responses
    with cluster_size without adding a cross-service JOIN at S6 (SA-4).

    Errors:
    - 401: missing or invalid X-Internal-JWT
    - 400: more than 100 doc_ids requested
    - 422: malformed request (invalid UUID, empty list)
    """
    try:
        sizes = await use_case.execute(body.doc_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchClusterSizesResponse(
        entries=[
            ClusterSizeEntry(
                doc_id=doc_id,
                cluster_size=result.cluster_size,
                # cluster_id=None when cluster_size=1 (no near-duplicate siblings)
                cluster_id=result.cluster_id,
            )
            for doc_id, result in sizes.items()
        ]
    )


@router.get("/documents/cluster/{cluster_id}/articles", response_model=ClusterArticlesResponse)
async def get_cluster_articles(
    cluster_id: UUID,
    use_case: ClusterArticlesUseCaseDep,
) -> ClusterArticlesResponse:
    """Fetch all sibling articles in a near-duplicate cluster.

    Internal endpoint — protected by InternalJWTMiddleware (PRD-0025, RS256).

    WHY this endpoint: the frontend "+N sim" chip needs to show the sibling
    articles when clicked.  The cluster_id comes from the existing
    ``cluster_size`` enrichment in the news/top response — the frontend passes
    it here to get the full article list for the drawer/sheet.

    A cluster always has exactly 2 participants (primary_doc_id +
    duplicate_doc_id in duplicate_clusters), so the response will contain
    0 articles (cluster not found) or 2 articles.

    Errors:
    - 401: missing or invalid X-Internal-JWT
    - 404: cluster_id not found in duplicate_clusters
    - 422: malformed cluster_id (not a valid UUID)
    """
    dtos = await use_case.execute(cluster_id)
    if not dtos:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return ClusterArticlesResponse(
        articles=[
            ClusterArticleResponse(
                id=dto.id,
                title=dto.title,
                url=dto.url,
                published_at=dto.published_at,
                source_name=dto.source_name,
                cluster_id=dto.cluster_id,
                cluster_size=dto.cluster_size,
            )
            for dto in dtos
        ]
    )
