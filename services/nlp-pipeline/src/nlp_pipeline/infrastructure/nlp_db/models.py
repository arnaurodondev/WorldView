"""SQLAlchemy 2.x ORM models for nlp_db.

These models MUST stay in sync with alembic/versions/0001_create_nlp_schema.py (BP-008/BP-019).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
from sqlalchemy import VARCHAR, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for nlp_db models."""


class SectionModel(Base):
    __tablename__ = "sections"

    section_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    section_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker: Mapped[str | None] = mapped_column(Text, nullable=True)  # transcripts only
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChunkModel(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sections.section_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_start_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentence_end_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_text_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChunkEmbeddingModel(Base):
    __tablename__ = "chunk_embeddings"

    embedding_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ready")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SectionEmbeddingModel(Base):
    __tablename__ = "section_embeddings"

    embedding_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sections.section_id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EntityMentionModel(Base):
    __tablename__ = "entity_mentions"

    mention_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sections.section_id", ondelete="SET NULL"),
        nullable=True,
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    mention_class: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ner_model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Added by migration 0007 (PLAN-0033 T-B-1-01)
    resolution_outcome: Mapped[str | None] = mapped_column(
        String(20),
        nullable=False,
        server_default="unresolved",
    )
    resolution_noise_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolution_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MentionResolutionModel(Base):
    """Audit trail for each resolution cascade stage (PRD §6.4.3)."""

    __tablename__ = "mention_resolutions"

    resolution_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mention_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entity_mentions.mention_id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    resolution_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DocumentEntityStatsModel(Base):
    """Per-document aggregated NER stats (PRD §6.4.3)."""

    __tablename__ = "document_entity_stats"

    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    distinct_mention_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    high_conf_mention_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    type_distribution: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChunkEntityMentionModel(Base):
    """Join table: chunk ↔ entity_mention by character-offset overlap."""

    __tablename__ = "chunk_entity_mentions"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("entity_mentions.mention_id", ondelete="CASCADE"),
        primary_key=True,
    )


class RoutingDecisionModel(Base):
    __tablename__ = "routing_decisions"

    decision_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    routing_tier: Mapped[str] = mapped_column(Text, nullable=False)
    final_routing_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    feature_scores_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    partition_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_avro: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetterQueueModel(Base):
    __tablename__ = "dead_letter_queue"

    dlq_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload_avro: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentSourceMetadataModel(Base):
    """Cached citation metadata for stored articles (PRD §6 Wave B-1).

    Populated by the S6 consumer; queried by S8 RAG for inline citations.
    Access is always by PK or batch IN clause — no additional indexes needed.
    """

    __tablename__ = "document_source_metadata"

    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_name: Mapped[str | None] = mapped_column(VARCHAR(100), nullable=True)
    source_type: Mapped[str | None] = mapped_column(VARCHAR(50), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # PRD-0026 §6.4: LLM relevance scoring columns (nullable; migration 0009)
    llm_relevance_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 4), nullable=True)
    llm_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmbeddingPendingModel(Base):
    """Retry queue for section/chunk embedding failures (migration 0004).

    Populated by the S6 consumer when Block 7 embedding calls fail.
    Consumed by EmbeddingRetryWorker which re-embeds with exponential backoff.
    """

    __tablename__ = "embedding_pending"

    pending_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    section_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ArticleImpactWindowModel(Base):
    """Multi-window price-impact measurements (PRD-0026 §6.4, migration 0009).

    One row per (article_id, entity_id, window_type). Replaces article_price_impacts.
    UNIQUE enforced by idx_article_impact_windows_unique index in migration 0009.
    """

    __tablename__ = "article_impact_windows"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    article_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_start: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8), nullable=False)
    price_end: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8), nullable=False)
    delta_pct: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6), nullable=False)
    high_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    low_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    impact_score: Mapped[Decimal] = mapped_column(sa.Numeric(6, 4), nullable=False)
    normalisation_cap_pct: Mapped[Decimal] = mapped_column(sa.Numeric(6, 2), nullable=False)
    data_quality: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default="daily_proxy")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
