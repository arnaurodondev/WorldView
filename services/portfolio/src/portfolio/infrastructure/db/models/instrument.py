"""SQLAlchemy ORM model for instrument references."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class InstrumentModel(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_instruments_symbol_exchange"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    symbol: Mapped[str]
    exchange: Mapped[str]
    name: Mapped[str | None] = mapped_column(default=None)
    currency: Mapped[str | None] = mapped_column(default=None)
    # PLAN-0053 T-D-4-02: NOT NULL after migration 0016, with server default
    # 'unknown' so manual-entry inserts without an explicit asset_class still
    # satisfy the constraint. We keep the Python default as ``"unknown"`` to
    # mirror that contract on in-memory ORM instances.
    asset_class: Mapped[str] = mapped_column(
        nullable=False,
        server_default=text("'unknown'"),
        default="unknown",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, default=None)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
