"""SQLAlchemy ORM model for the ``earnings_calendar`` table.

WHY THIS MODEL EXISTS (PLAN-0089 Wave L-5c):
  The ``earnings_calendar`` table has existed since alembic migration 001
  (``services/market-data/alembic/versions/001_initial_schema.py``) but was
  never reflected in the SQLAlchemy ORM layer — until now there were no
  callers that needed to read/write it via the ORM. L-5c surfaces the
  ``next_earnings_date`` snapshot field which depends on this table
  (``SELECT MIN(report_date) FROM earnings_calendar WHERE instrument_id = :id
  AND report_date >= CURRENT_DATE``), so the missing model becomes a
  blocker for testable, type-checked queries.

R12 (domain-layer purity): this is an infrastructure model. No domain
layer imports it.

NOTE ON OWNERSHIP: the table is currently *unpopulated* in production —
L-5b (S3 sync worker / EODHD ``/calendar/earnings`` consumer) is a
**deferred** wave and remains the future owner of writes. L-5c only adds
the read-side ORM so the snapshot writer and any future consumer can use
the same model.

SCHEMA MIRRORS MIGRATION 001:
  - PK: ``id`` UUID with server-side ``gen_random_uuid()`` default
  - FK: ``instrument_id`` → ``instruments.id`` ON DELETE CASCADE
  - Unique constraint ``uq_earnings_calendar`` on
    (``instrument_id``, ``report_date``)
  - Indexes:
      * ``ix_earnings_calendar_report_date`` on (``report_date``)
      * ``ix_earnings_calendar_instrument`` on (``instrument_id``)
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class EarningsCalendarModel(Base):
    """One scheduled earnings report row (matches migration 001 schema).

    NULL semantics:
      * ``fiscal_date`` / ``eps_estimate`` / ``eps_actual`` / ``before_after``
        / ``currency`` are nullable because EODHD ``/calendar/earnings``
        responses often omit these for upcoming (future) reports.
      * ``report_date`` is NOT NULL — every row represents one calendar
        entry keyed by (instrument, report_date).
    """

    __tablename__ = "earnings_calendar"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # mirrors ix_earnings_calendar_instrument from migration 001
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fiscal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    eps_estimate: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    # "BeforeMarket" / "AfterMarket" / "DuringMarket"
    before_after: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
