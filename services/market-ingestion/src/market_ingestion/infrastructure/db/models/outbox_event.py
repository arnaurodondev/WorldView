"""SQLAlchemy 2.0 ORM model for outbox_events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class OutboxEventModel(Base):
    """ORM model for the ``outbox_events`` table.

    Transactional outbox for reliable Kafka publishing.
    Lease-based locking ensures concurrent dispatcher safety.
    """

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Tracing
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Kafka targeting
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Event type for routing (avoids parsing headers on hot path)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)

    # Status: pending → in_flight → published | retry → dead
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lease-based locking
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Retry scheduling
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Dispatcher claim: eligible rows by status + lease expiry
        Index("ix_outbox_events_claimable", "status", "locked_until"),
        # Retry scheduling
        Index("ix_outbox_events_retry", "status", "next_attempt_at"),
        # Event-type routing
        Index("ix_outbox_events_event_type", "event_type"),
        # FIFO ordering for dispatcher
        Index("ix_outbox_events_created_at", "created_at"),
    )
