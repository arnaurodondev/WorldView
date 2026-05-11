"""Pydantic request/response schemas for the tenant document upload endpoints.

PLAN-0086 Wave E-2.

These models define the HTTP contract between S4 and its callers (S9 gateway
and tests).  They are deliberately separate from the domain entities — the API
layer never leaks domain internals, and the domain layer never imports from
``api/``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response body for a successful POST /api/v1/documents/upload (202 Accepted).

    The document is queued for async processing; ``status`` will be
    ``"processing"`` until the pipeline stages complete.
    """

    doc_id: UUID
    status: str
    title: str
    filename: str


class DocumentStatusResponse(BaseModel):
    """Full status for a single tenant document (GET /api/v1/documents/{doc_id}).

    Pipeline-output fields (``word_count``, ``chunk_count``, ``ready_at``) are
    None until the corresponding pipeline stage populates them.
    """

    doc_id: UUID
    title: str
    filename: str
    status: str
    word_count: int | None = None
    chunk_count: int | None = None
    uploaded_at: datetime
    ready_at: datetime | None = None
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated list of tenant documents (GET /api/v1/documents).

    ``next_cursor`` is None on the last page — pass it as the ``cursor``
    query param on subsequent requests to advance the page.
    """

    items: list[DocumentStatusResponse]
    next_cursor: str | None = None
    total: int


class DeleteResponse(BaseModel):
    """Response body for a successful DELETE /api/v1/documents/{doc_id} (200 OK).

    Returns 200 (not 204) so the response body is always present — BP-064.
    """

    doc_id: UUID
    status: str
