"""ORM model for the fundamental_metrics read-optimized projection table.

One row per (instrument_id, as_of_date, metric, period_type).  Derived from
the 18 fundamentals section tables and populated on write for efficient
timeseries queries and screening.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class FundamentalMetricModel(Base):
    __tablename__ = "fundamental_metrics"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(Numeric(24, 6), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "as_of_date",
            "metric",
            "period_type",
            name="uq_fundamental_metrics_instrument_date_metric",
        ),
    )
