"""SQLAlchemy ORM model for the ``quotes`` table.

Latest bid/ask/last snapshot per instrument (last-write-wins).
Primary key is ``instrument_id`` — one row per instrument.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class QuoteModel(Base):
    """Latest quote snapshot for a trading instrument.

    Not a time-series table — stores only the most recent quote.
    Full price history is stored in ``ohlcv_bars``.
    """

    __tablename__ = "quotes"

    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bid: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    ask: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    last: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    volume: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
