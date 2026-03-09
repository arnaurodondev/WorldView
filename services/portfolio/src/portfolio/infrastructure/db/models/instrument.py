"""SQLAlchemy ORM model for instrument references."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint, func
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
    asset_class: Mapped[str | None] = mapped_column(default=None)
    source_event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
