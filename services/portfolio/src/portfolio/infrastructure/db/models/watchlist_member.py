"""ORM model for WatchlistMember."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class WatchlistMemberModel(Base):
    __tablename__ = "watchlist_members"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "entity_id", name="uq_watchlist_members_watchlist_entity"),
        Index("ix_watchlist_members_entity_id", "entity_id"),
        Index("ix_watchlist_members_watchlist_id", "watchlist_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    watchlist_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("watchlists.id"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="company")
    # PLAN-0046 / T-46-2-01: denormalised ticker/name/instrument_id resolved at
    # add-time. Nullable so historical rows (pre-Alembic 0010) keep working;
    # the read path interprets NULL as "not yet resolved". See migration docstring.
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, default=None)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # REQ-002b (migration 0019): nullable idempotency key. Uniqueness enforced
    # by partial index ``uq_watchlist_members_watchlist_idempotency_key``.
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, default=None)
