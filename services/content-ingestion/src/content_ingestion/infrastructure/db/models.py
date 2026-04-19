"""SQLAlchemy 2.x ORM models for the Content Ingestion service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceModel(Base):
    """Configured polling source."""

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceAdapterStateModel(Base):
    """Per-source watermark state for incremental polling."""

    __tablename__ = "source_adapter_state"

    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), primary_key=True)
    last_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FetchLogModel(Base):
    """Record of a single URL fetch attempt."""

    __tablename__ = "article_fetch_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_article_fetch_log_url_hash"),
        Index("ix_article_fetch_log_source", "source_id", "fetched_at"),
    )


class OutboxEventModel(Base):
    """Transactional outbox event — canonical schema.

    Column names follow OutboxRecordProtocol from libs/messaging:
      - ``attempts``    -> dispatch attempt counter
      - ``leased_until``-> lease expiry (None = unlocked)
    """

    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="content.article.raw.v1")
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


class ContentIngestionTaskModel(Base):
    """Scheduler-worker task queue — each row represents a single fetch cycle for one source."""

    __tablename__ = "content_ingestion_tasks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_cit_status_created", "status", "created_at"),
        Index(
            "ix_cit_source_window",
            "source_id",
            "window_start",
            unique=True,
            postgresql_where=text("window_start IS NOT NULL"),
        ),
        Index("ix_cit_worker_lease", "worker_id", "lease_expires"),
    )


class PredictionMarketFetchLogModel(Base):
    """Deduplication log for Polymarket poll cycles.

    Each row records a market snapshot captured during a single poll.
    The unique index on ``(market_id, snapshot_at)`` prevents double-publishing
    the same market state within a single poll window.

    Notes:
        - ``id`` is always app-generated via ``new_uuid7()`` (BP: no gen_random_uuid() on PKs)
        - ``resolution_status`` carries a server_default of ``'open'`` (BP-126)
        - ``source_id`` is nullable to allow manual/webhook snapshot submissions
    """

    __tablename__ = "prediction_market_fetch_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=True)
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default=text("'open'"),
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market_id", "snapshot_at", name="uq_pmfl_market_snapshot"),
        Index("ix_pmfl_source_fetched", "source_id", "fetched_at"),
    )


class DeadLetterQueueModel(Base):
    """Failed events moved from the outbox for manual resolution."""

    __tablename__ = "dead_letter_queue"

    dlq_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    original_event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload_avro: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
