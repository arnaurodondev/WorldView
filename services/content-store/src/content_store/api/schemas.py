"""Pydantic request/response models for S5 API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── DLQ ──────────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None


class DLQListResponse(BaseModel):
    entries: list[DLQEntryResponse]
    count: int


class DLQResolveRequest(BaseModel):
    note: str = Field(..., max_length=2000)


# ── Batch documents ───────────────────────────────────────────────────────────


class BatchDocumentsRequest(BaseModel):
    # max_length not enforced here — use case raises DomainError (→ 400) for >50
    doc_ids: list[UUID] = Field(..., min_length=1)


class DocumentMetadataResponse(BaseModel):
    doc_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    source_type: str | None
    word_count: int | None


class BatchDocumentsResponse(BaseModel):
    documents: list[DocumentMetadataResponse]


# ── Batch cluster sizes ───────────────────────────────────────────────────────


class BatchClusterSizesRequest(BaseModel):
    """Request body for POST /api/v1/documents/cluster-sizes."""

    # Max 100 enforced in the use case; validated here for early 422 rejection.
    doc_ids: list[UUID] = Field(..., min_length=1, max_length=100)


class ClusterSizeEntry(BaseModel):
    """Cluster size and cluster_id for a single document.

    WHY cluster_id added (P2-F): the frontend "+N sim" chip needs to open a
    "similar articles" drawer.  To fetch the drawer contents, the frontend
    calls GET /v1/news/cluster/{cluster_id}.  cluster_id is None when the
    document has no near-duplicate siblings (cluster_size=1).
    """

    doc_id: UUID
    # WHY cluster_size (not sibling_count): cluster_size includes the document
    # itself, so cluster_size=1 means "no duplicates" and cluster_size=3 means
    # "this doc + 2 near-duplicate siblings".
    cluster_size: int
    # Forward-compatible addition — None when cluster_size == 1.
    cluster_id: UUID | None = None


class BatchClusterSizesResponse(BaseModel):
    """Response for POST /api/v1/documents/cluster-sizes."""

    entries: list[ClusterSizeEntry]


# ── Cluster articles ──────────────────────────────────────────────────────────


class ClusterArticleResponse(BaseModel):
    """Single article in a near-duplicate cluster.

    WHY id (not doc_id): the frontend uses "id" as the canonical field name
    for article identifiers in the cluster modal context.  Consistent with
    how /v1/news/cluster/{id} will expose these to the frontend via S9.
    """

    id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    cluster_id: UUID
    cluster_size: int


class ClusterArticlesResponse(BaseModel):
    """Response for GET /api/v1/documents/cluster/{cluster_id}/articles."""

    articles: list[ClusterArticleResponse]
