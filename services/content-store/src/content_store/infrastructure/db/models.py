"""SQLAlchemy 2.x ORM models for the Content Store service."""

from __future__ import annotations

from datetime import datetime  # — SQLAlchemy resolves Mapped[datetime] via get_type_hints() at runtime
from uuid import UUID  # — SQLAlchemy resolves Mapped[UUID] via get_type_hints() at runtime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── documents ──────────────────────────────────────────────────────────────────


class DocumentModel(Base):
    """Canonical deduplicated document."""

    __tablename__ = "documents"

    doc_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="stored", server_default=text("'stored'"))
    dedup_result: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unique", server_default=text("'unique'")
    )
    minio_silver_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    corroborates_doc_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_documents_normalized_hash", "normalized_hash"),
        Index("idx_documents_source_published", "source_type", published_at.desc()),
        Index(
            "idx_documents_corroborates",
            "corroborates_doc_id",
            postgresql_where=text("corroborates_doc_id IS NOT NULL"),
        ),
    )


# ── dedup_hashes ───────────────────────────────────────────────────────────────


class DedupHashModel(Base):
    """Hash tracking for Stage A (raw SHA-256) and Stage B (normalized SHA-256)."""

    __tablename__ = "dedup_hashes"

    hash_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    doc_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False
    )
    hash_type: Mapped[str] = mapped_column(String(30), nullable=False)
    hash_value: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("hash_type", "hash_value", name="uq_dedup_hashes_type_value"),
        Index("idx_dedup_hashes_lookup", "hash_type", "hash_value"),
    )


# ── duplicate_clusters ─────────────────────────────────────────────────────────


class DuplicateClusterModel(Base):
    """Tracks pairs of documents identified as duplicates/corroborating."""

    __tablename__ = "duplicate_clusters"

    cluster_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    primary_doc_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("documents.doc_id"), nullable=False)
    duplicate_doc_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.doc_id"), nullable=False
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("primary_doc_id", "duplicate_doc_id", name="uq_duplicate_clusters_pair"),)


# ── minhash_signatures ─────────────────────────────────────────────────────────


class MinHashSignatureModel(Base):
    """128-band MinHash vector for a document.

    CRITICAL: ``signature`` is ``INTEGER[]``, NEVER ``BYTEA``.
    """

    __tablename__ = "minhash_signatures"

    sig_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    doc_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    signature: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    shingle_type: Mapped[str] = mapped_column(String(50), nullable=False, default="word_bigram_char3gram")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_minhash_sig_created", created_at.desc()),)


# ── minhash_entity_mentions ────────────────────────────────────────────────────


class MinHashEntityMentionModel(Base):
    """Entity mention extracted from a document's MinHash signature.

    ``entity_id`` is a logical FK to intelligence_db — NO Postgres constraint.
    """

    __tablename__ = "minhash_entity_mentions"

    sig_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("minhash_signatures.sig_id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_text_hash: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mention_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNRESOLVED")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_minhash_mentions_hash", "mention_text_hash", "sig_id"),
        Index(
            "idx_minhash_mentions_entity",
            "entity_id",
            "sig_id",
            postgresql_where=text("entity_id IS NOT NULL"),
        ),
    )


# ── outbox_events ──────────────────────────────────────────────────────────────


class OutboxEventModel(Base):
    """Transactional outbox event — canonical schema.

    Column names follow OutboxRecordProtocol from libs/messaging.
    """

    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="content.article.stored.v1")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_outbox_claimable",
            "status",
            "leased_until",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )


# ── processed_events ───────────────────────────────────────────────────────────


class ProcessedEventModel(Base):
    """Idempotency table for the article consumer.

    ``event_id`` is the Avro envelope ``event_id`` field extracted from each
    consumed Kafka message.  Inserted atomically with the article document
    write so the consumer never re-processes an event that was already stored.
    """

    __tablename__ = "processed_events"

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_processed_events_processed_at", "processed_at"),)


# ── dead_letter_queue ──────────────────────────────────────────────────────────


class DeadLetterQueueModel(Base):
    """Failed events moved from the outbox for manual resolution."""

    __tablename__ = "dead_letter_queue"

    dlq_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    original_event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregate_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload_avro: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
