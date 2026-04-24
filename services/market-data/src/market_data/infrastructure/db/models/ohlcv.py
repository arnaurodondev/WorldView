"""SQLAlchemy ORM model for the ``ohlcv_bars`` table.

This table is defined as a standard PostgreSQL table here; migration 002
converts it to a TimescaleDB hypertable partitioned on ``bar_date``.
The composite primary key is ``(instrument_id, timeframe, bar_date)``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class OHLCVBarModel(Base):
    """Single OHLCV candlestick bar for an instrument at a given timeframe.

    Price fields use ``NUMERIC(18,8)`` and volume uses ``NUMERIC(24,8)`` to avoid float precision
    loss.  ``provider_priority`` drives the ON CONFLICT update guard in the
    bulk-upsert repository method.
    """

    __tablename__ = "ohlcv_bars"
    __table_args__ = (Index("ix_ohlcv_bars_instrument_bar_date", "instrument_id", "bar_date"),)

    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timeframe: Mapped[str] = mapped_column(String(5), primary_key=True)
    bar_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False, server_default="0")
    adjusted_close: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    # True for bars derived locally from daily bars (PLAN-0036 W2-4).
    # server_default="false" ensures forward-compat with existing rows.
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
