"""SQLAlchemy ORM model for brokerage_connections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class BrokerageConnectionModel(Base):
    __tablename__ = "brokerage_connections"
    __table_args__ = (
        Index("ix_brokerage_connections_user_status", "user_id", "status"),
        Index("ix_brokerage_connections_tenant_id", "tenant_id"),
        Index("ix_brokerage_connections_portfolio_id", "portfolio_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=False)
    snaptrade_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    snaptrade_user_secret: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    brokerage_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    snaptrade_tos_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
