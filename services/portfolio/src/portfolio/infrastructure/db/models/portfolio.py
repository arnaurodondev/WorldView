"""SQLAlchemy ORM model for portfolios."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class PortfolioModel(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_portfolios_owner_name"),
        Index("ix_portfolios_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str]
    currency: Mapped[str] = mapped_column(default="USD")
    status: Mapped[str] = mapped_column(default="active")
    # PLAN-0046 Wave 3 / T-46-3-01. ``kind`` is added by Alembic migration 0011
    # with ``server_default='manual'`` so existing rows backfill safely (BP-126).
    # The mapped_column also carries ``default='manual'`` for ORM-level INSERTs.
    kind: Mapped[str] = mapped_column(default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # REQ-002a (migration 0019): caller-supplied Idempotency-Key — nullable
    # so legacy rows + non-idempotent callers remain valid. Uniqueness is
    # enforced by a partial unique index on (tenant_id, idempotency_key).
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, default=None)
    # PLAN-0114 W1: cost basis algorithm column (migration 0024).
    # BP-126: server_default="FIFO" ensures all existing rows get a safe default.
    cost_basis_method: Mapped[str] = mapped_column(default="FIFO", server_default="FIFO")
