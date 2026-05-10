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
    """Cluster size for a single document."""

    doc_id: UUID
    # WHY cluster_size (not sibling_count): cluster_size includes the document
    # itself, so cluster_size=1 means "no duplicates" and cluster_size=3 means
    # "this doc + 2 near-duplicate siblings".
    cluster_size: int


class BatchClusterSizesResponse(BaseModel):
    """Response for POST /api/v1/documents/cluster-sizes."""

    entries: list[ClusterSizeEntry]
