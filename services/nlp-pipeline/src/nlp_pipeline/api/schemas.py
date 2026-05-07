"""Pydantic request/response schemas for the NLP Pipeline REST API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
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


class EntityArticleItem(BaseModel):
    """One article mentioning a specific entity (for GET /entities/{id}/articles)."""

    article_id: str
    title: str
    url: str
    published_at: datetime
    source_name: str
    source_type: str | None = None
    display_relevance_score: float | None = None
    primary_entity_id: str


class EntityArticlesResponse(BaseModel):
    """Response for GET /api/v1/entities/{entity_id}/articles (rag-chat feed)."""

    articles: list[EntityArticleItem]
    entity_id: str
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
    # PLAN-0063 W5-3: hybrid retrieval substrate.
    #   "ann"     — vector-only ANN (HNSW) — current default, requires query_text OR query_embedding
    #   "lexical" — Postgres FTS (tsv_english + tsv_simple GREATEST) — requires query_text
    #   "hybrid"  — both legs in parallel + RRF fusion — requires query_text
    # Hybrid + lexical both run BM25-style FTS server-side so they cannot fall
    # back to a pure embedding (the `_search_type_requires_query_text` validator
    # below enforces this). The orchestrator at S8 decides which mode to use
    # inline (per L11 — no plan flag).
    search_type: Literal["ann", "lexical", "hybrid"] = "ann"
    # PLAN-0078 Wave C: optional entity filter via GIN-indexed chunks.entity_mentions JSONB.
    # Filter semantics (§3): OR within each field, AND across fields.
    #   entity_ids=[A, B]             → chunks mentioning A OR B
    #   entity_types=["company"]      → chunks with any company mention
    #   entity_ids=[A] + entity_types=["company"] → chunks where a SINGLE mention
    #                                  has entity_id=A AND entity_type=company
    # Both fields default to None → no entity filter (full unfiltered results).
    entity_ids: list[UUID] | None = Field(default=None, max_length=50)
    entity_types: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def exactly_one_query(self) -> ChunkSearchRequest:
        # ANN mode keeps the strict "exactly one" rule because the use case
        # picks the embedding path when `query_embedding` is set, and the
        # text path otherwise. The hybrid/lexical modes loosen this — a
        # caller can supply both (the embedding feeds the ANN leg, the text
        # feeds the FTS leg) — so we only enforce exclusivity when the
        # search_type is the default ANN.
        if self.search_type == "ann" and (self.query_text is None) == (self.query_embedding is None):
            raise ValueError("Exactly one of query_text or query_embedding must be provided")
        return self

    @model_validator(mode="after")
    def _search_type_requires_query_text(self) -> ChunkSearchRequest:
        # Lexical and hybrid search both run a Postgres FTS query that has no
        # meaningful interpretation of a raw embedding vector — they need the
        # original surface text. Reject early at the API boundary so the
        # caller gets a 422 instead of an ambiguous downstream error.
        if self.search_type in ("lexical", "hybrid") and not self.query_text:
            raise ValueError(f"search_type={self.search_type!r} requires query_text")
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


# ── Ranked news (PRD-0026 §6.2) ──────────────────────────────────────────────


class ImpactWindows(BaseModel):
    """Per-window price-impact scores for a single article (PRD-0026 §6.5)."""

    day_t0: float | None = None
    day_t1: float | None = None
    day_t2: float | None = None
    day_t5: float | None = None


class RankedArticleResponse(BaseModel):
    """One article in a ranked news feed response (PRD-0026 §6.2)."""

    article_id: UUID
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    source_type: str | None = None
    source_name: str | None = None
    routing_tier: str | None = None
    routing_score: float | None = None
    market_impact_score: float | None = None
    llm_relevance_score: float | None = None
    display_relevance_score: float = Field(ge=0.0)
    # Only present for global top-news endpoint; None for entity article endpoint.
    primary_entity_id: UUID | None = None
    primary_entity_symbol: str | None = None
    # Nested window scores; None when the article has no price-impact data yet.
    impact_windows: ImpactWindows | None = None
    # PLAN-0050 Wave E: article-level sentiment + convenience impact score.
    # sentiment: "positive" | "negative" | "neutral" | "mixed"; null until the
    # ArticleRelevanceScoringWorker processes this article (LIGHT-tier skipped).
    # impact_score: MAX(day_t0, day_t1) aggregated from article_impact_windows;
    # null until PriceImpactLabellingWorker computes price windows (< 25h articles).
    sentiment: str | None = None
    impact_score: float | None = None


class RankedNewsResponse(BaseModel):
    """Paginated ranked news response (used by both top-news and entity-articles)."""

    articles: list[RankedArticleResponse]
    total: int


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
