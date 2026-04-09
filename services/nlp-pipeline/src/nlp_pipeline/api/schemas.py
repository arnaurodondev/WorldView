"""Pydantic request/response schemas for the NLP Pipeline REST API."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ── Signal schemas ────────────────────────────────────────────────────────────


class SignalResponse(BaseModel):
    signal_id: UUID
    doc_id: UUID
    entity_id: UUID
    signal_type: str
    confidence: float
    evidence_text: str
    detected_at: datetime
    market_impact_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
    limit: int
    offset: int


# ── Entity search ─────────────────────────────────────────────────────────────


class EntitySearchResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int


class EntityListResponse(BaseModel):
    items: list[EntitySearchResponse]
    total: int
    limit: int
    offset: int


class EntityDetailResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    mention_count: int
    resolved_count: int  # auto-resolved mentions
    provisional_count: int  # unresolved / provisional


class EntityArticleResponse(BaseModel):
    doc_id: UUID
    source_type: str
    published_at: datetime | None
    routing_tier: str
    mention_count: int


class EntityArticlesResponse(BaseModel):
    entity_id: UUID
    items: list[EntityArticleResponse]
    total: int


# ── Vector search ─────────────────────────────────────────────────────────────


class VectorSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class VectorSearchHit(BaseModel):
    doc_id: UUID
    section_id: UUID
    score: float
    snippet: str


class VectorSearchResponse(BaseModel):
    query: str
    hits: list[VectorSearchHit]


# ── Entity resolve (Wave B-2) ─────────────────────────────────────────────────


class EntityResolveRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=2000)
    top_k_per_mention: int = Field(default=3, ge=1, le=10)
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)


class ResolvedEntityResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float
    ticker: str | None
    isin: str | None
    matched_text: str
    resolution_stage: int


class EntityResolveResponse(BaseModel):
    entities: list[ResolvedEntityResponse]
    query_text_normalized: str


# ── Enhanced chunk search (Wave B-3) ─────────────────────────────────────────


class ChunkSearchRequest(BaseModel):
    query_text: str | None = Field(None, min_length=1, max_length=2000)
    query_embedding: list[float] | None = Field(None, min_length=1024, max_length=1024)
    granularity: str = Field(default="chunk", pattern="^(chunk|section|both)$")
    top_k: int = Field(default=20, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    include_entities: bool = True
    date_from: date | None = None
    date_to: date | None = None
    source_types: list[str] = []

    @model_validator(mode="after")
    def exactly_one_query(self) -> ChunkSearchRequest:
        if (self.query_text is None) == (self.query_embedding is None):
            raise ValueError("Exactly one of query_text or query_embedding must be provided")
        return self


class ChunkEntityAnnotationResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float


class SourceMetadataResponse(BaseModel):
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    source_type: str | None


class EnrichedChunkResultResponse(BaseModel):
    chunk_id: UUID
    doc_id: UUID
    section_id: UUID | None
    granularity: str
    text: str
    score: float
    source_metadata: SourceMetadataResponse
    entities: list[ChunkEntityAnnotationResponse]
    section_type: str | None
    heading_path: str | None


class ChunkSearchResponse(BaseModel):
    results: list[EnrichedChunkResultResponse]
    total_searched: int
    embedding_model: str


# ── Reprocess ─────────────────────────────────────────────────────────────────


class ReprocessResponse(BaseModel):
    article_id: UUID
    status: str  # "queued" | "not_found"
    message: str


# ── DLQ schemas ───────────────────────────────────────────────────────────────


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
    total: int


class DLQResolveRequest(BaseModel):
    note: str = Field(default="", max_length=1024)
