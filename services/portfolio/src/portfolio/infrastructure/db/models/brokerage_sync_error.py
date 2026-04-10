"""SQLAlchemy ORM model for brokerage_sync_errors."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class BrokerageTransactionSyncErrorModel(Base):
    __tablename__ = "brokerage_sync_errors"
    __table_args__ = (
        Index("ix_brokerage_sync_errors_connection_created", "connection_id", "created_at"),
        Index("ix_brokerage_sync_errors_error_type", "error_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brokerage_connections.id"), nullable=False
    )
    snaptrade_transaction_id: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(50), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_transaction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
