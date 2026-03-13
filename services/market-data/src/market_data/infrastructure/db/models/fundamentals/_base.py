"""Shared base mixin for all fundamentals ORM models.

Each fundamentals table stores section-specific key/value data in a
``JSONB`` column alongside common metadata columns (instrument_id,
period_type, period_end_date).  The surrogate UUID primary key allows
multiple periods per instrument.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class FundamentalsModelMixin:
    """Common columns shared by all 14 fundamentals tables."""

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
