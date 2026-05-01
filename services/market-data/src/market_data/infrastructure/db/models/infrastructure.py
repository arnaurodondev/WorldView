"""SQLAlchemy ORM models for infrastructure/operational tables.

Three tables:
- ``ingestion_events`` — idempotency dedup for Kafka consumer events.
- ``failed_tasks``     — retry queue for consumer processing failures.
- ``outbox_events``   — transactional outbox for domain event publishing.

Legacy column-mismatch fixes applied here (see wave-02 handoff evidence):

``failed_tasks``:
  Legacy had columns: ``event_id``, ``event_type``, ``error_message``,
  ``attempt_count``, ``next_retry_at`` (no ``payload``, no ``status``).
  Worldview introduces: ``task_type``, ``payload JSONB``, ``attempts``,
  ``max_attempts``, ``next_attempt_at``, ``last_error``, ``status``.

``outbox_events``:
  Legacy used ``leased_until`` for the lease expiry column.
  Worldview uses ``lease_expires_at`` (matches ``OutboxRecordProtocol``).
  Added: ``claimed_by``, ``claimed_at``, ``dispatched_at`` columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class IngestionEventModel(Base):
    """Idempotency record for a processed Kafka ingestion event.

    ``event_id`` carries a UNIQUE constraint (not PK) so the dedup check
    can use a fast index scan.  The surrogate ``id`` is the actual PK.

    ``content_sha256`` holds the canonical-object SHA-256 from the
    ``MarketDatasetFetched`` envelope.  Indexed for content-based dedup:
    if a later event carries the same SHA-256 for the same dataset_type, the
    consumer can skip re-processing identical data without downloading from
    object storage.
    """

    __tablename__ = "ingestion_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_ingestion_events_event_id"),)

    id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class FailedTaskModel(Base):
    """Retry queue for consumer processing failures.

    Column fix vs legacy: replaced ``event_id/event_type/error_message/
    attempt_count/next_retry_at`` with ``task_type/payload/attempts/
    max_attempts/next_attempt_at/last_error/status``.
    """

    __tablename__ = "failed_tasks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class OutboxEventModel(Base):
    """Transactional outbox record for domain event publishing.

    Column fix vs legacy: renamed ``leased_until`` → ``lease_expires_at``,
    added ``claimed_by``, ``claimed_at``, ``dispatched_at``.

    PLAN-0057-followup Wave B (F-DATA-06): added ``partition_key`` to carry
    the optional Kafka partition key forward into the dispatcher. NULL =
    legacy semantic (round-robin partitioning); see migration 014 and
    ``libs/messaging`` ``OutboxRecordProtocol.partition_key`` docstring for
    details.
    """

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    # F-DATA-06: optional Kafka partition key for per-aggregate ordering.
    # NULL → dispatcher passes ``key=None`` (Kafka round-robin), preserving
    # legacy behaviour. Producers opt in by passing ``partition_key=`` to
    # ``OutboxEventRepository.create``.
    partition_key: Mapped[str | None] = mapped_column(String, nullable=True)
