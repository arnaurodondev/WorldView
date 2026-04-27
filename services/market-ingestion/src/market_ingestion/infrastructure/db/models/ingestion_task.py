"""SQLAlchemy 2.0 ORM model for ingestion_tasks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class IngestionTaskModel(Base):
    """ORM model for the ``ingestion_tasks`` table.

    Idempotent enqueue via the ``uq_ingestion_tasks_dedupe_key`` constraint.
    Claim-batch performance via ``ix_ingestion_tasks_claimable`` index.
    Scheduler duplicate-prevention via ``ix_ingestion_tasks_active_check``.
    """

    __tablename__ = "ingestion_tasks"

    # Primary key — UUIDv7 / ULID for time-sortable ordering
    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Provider and dataset identification
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Instrument targeting
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Timeframe (OHLCV only)
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Date range (OHLCV backfills)
    range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # State machine
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lease-based locking (domain: lease_owner / lease_expires)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Idempotent enqueue key
    dedupe_key: Mapped[str] = mapped_column(String(500), nullable=False)

    # Backfill marker
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Result reference (populated on SUCCEEDED; NULL for PENDING/RUNNING/RETRY/FAILED)
    result_ref_bucket: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref_mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provider tracking (PRD-0032 / PLAN-0040 A-1 migration 0010)
    # Records which provider actually fetched the data.  NULL for tasks that
    # have not yet SUCCEEDED.  Forward-compatible: historical rows remain NULL.
    fetched_by_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Claim-batch performance: status + lease + next_attempt + ordering
        Index(
            "ix_ingestion_tasks_claimable",
            "status",
            "locked_until",
            "next_attempt_at",
            "created_at",
        ),
        # Idempotent enqueue unique constraint
        Index(
            "uq_ingestion_tasks_dedupe_key",
            "provider",
            "dedupe_key",
            unique=True,
        ),
        # Monitoring / status overview
        Index("ix_ingestion_tasks_status", "status"),
        # Symbol lookups
        Index("ix_ingestion_tasks_symbol", "symbol"),
        # Provider + status for filtered queries
        Index("ix_ingestion_tasks_provider_status", "provider", "status"),
        # Scheduler duplicate-prevention (has_active_task)
        Index(
            "ix_ingestion_tasks_active_check",
            "provider",
            "dataset_type",
            "symbol",
            "exchange",
            "timeframe",
            "dataset_variant",
            "status",
        ),
    )
