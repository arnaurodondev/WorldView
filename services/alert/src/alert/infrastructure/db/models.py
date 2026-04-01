"""SQLAlchemy ORM models for alert_db.

Maps 1:1 to the DDL in ``alembic/versions/0001_create_alert_db.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all alert_db models."""

    type_annotation_map: ClassVar[dict[type, type]] = {}  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# alert_subscriptions
# ---------------------------------------------------------------------------


class AlertSubscriptionModel(Base):
    __tablename__ = "alert_subscriptions"

    subscription_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    alert_types: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", "watchlist_id"),
        Index("idx_subscriptions_entity", "entity_id", postgresql_where="deleted_at IS NULL"),
        Index("idx_subscriptions_user", "user_id", postgresql_where="deleted_at IS NULL"),
    )


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


class AlertModel(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_topic: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_alerts_entity", "entity_id", created_at.desc()),)


# ---------------------------------------------------------------------------
# alert_deliveries
# ---------------------------------------------------------------------------


class AlertDeliveryModel(Base):
    __tablename__ = "alert_deliveries"

    delivery_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("alerts.alert_id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, server_default="websocket")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="delivered")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_deliveries_alert", "alert_id"),
        Index("idx_deliveries_user_pending", "user_id", created_at.desc(), postgresql_where="status = 'pending'"),
    )


# ---------------------------------------------------------------------------
# pending_alerts
# ---------------------------------------------------------------------------


class PendingAlertModel(Base):
    __tablename__ = "pending_alerts"

    pending_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    alert_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("alerts.alert_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "alert_id"),
        Index("idx_pending_alerts_user", "user_id", "created_at", postgresql_where="delivered_at IS NULL"),
    )


# ---------------------------------------------------------------------------
# outbox_events
# ---------------------------------------------------------------------------


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    partition_key: Mapped[str] = mapped_column(String, nullable=False)
    payload_avro: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_outbox_s10_pending", "created_at", postgresql_where="status = 'pending'"),)


# ---------------------------------------------------------------------------
# dead_letter_queue
# ---------------------------------------------------------------------------


class DeadLetterQueueModel(Base):
    __tablename__ = "dead_letter_queue"

    dlq_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    original_event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_avro: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
