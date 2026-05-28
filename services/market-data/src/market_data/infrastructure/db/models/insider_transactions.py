"""ORM model for the ``insider_transactions`` table.

WHY THIS MODEL EXISTS (PLAN-0089 Wave L-4b):

The existing ``insider_transactions_snapshot`` table (FIX-F7) stores a
single embedded summary blob from the EODHD Fundamentals payload — useful
for a quick "any insider activity?" check but useless for ranking instruments
by trailing-90-day net dollar flow (the L-4b screener column "INSIDER 90D").

This new table stores one row per discrete insider transaction returned by
the dedicated EODHD ``/insider-transactions`` endpoint, with the columns
needed to compute a per-instrument 90d rollup:

  * ``net_value_usd`` (derived = ``shares * price_per_share`` with sign
    flipped for SELL/GIFT) — the rollup worker sums this over the trailing
    90 days into ``instrument_fundamentals_snapshot.insider_net_buy_90d``.

The natural key ``(instrument_id, filer_name, transaction_date,
transaction_type, shares)`` allows the consumer to do an idempotent
INSERT … ON CONFLICT DO NOTHING (BP-590-safe). EODHD does not expose a
stable transaction id, so the natural key is the only handle we have.

Schema choices:
  * NUMERIC(20,4) for shares/price — enough headroom for any realistic
    insider lot; the 4-digit scale covers fractional shares.
  * NUMERIC(20,2) for ``net_value_usd`` — currency in cents granularity.
  * CHECK constraint on ``transaction_type`` keeps the column closed-set;
    new EODHD codes will be rejected by the consumer (logged + DLQ).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base


class InsiderTransactionModel(Base):
    """One row per insider transaction from EODHD ``/insider-transactions``.

    PLAN-0089 Wave L-4b. The rollup worker
    (``application/use_cases/rollup_insider_90d.py``) sums ``net_value_usd``
    over the trailing 90 days per ``instrument_id`` and writes the result
    into ``instrument_fundamentals_snapshot.insider_net_buy_90d``.
    """

    __tablename__ = "insider_transactions"

    # WHY UUIDv7 PK (not natural-key PK): natural key may evolve as EODHD
    # adds optional fields; surrogate PK keeps the table stable. The natural
    # key is enforced as a UNIQUE constraint instead.
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
    )

    filer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    filer_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    price_per_share: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    # Derived = ``shares * price_per_share`` with sign negative for SELL/GIFT;
    # NULL when ``price_per_share`` is missing from the EODHD payload.
    net_value_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True
    )

    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'EODHD'"),
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("(now() AT TIME ZONE 'utc')"),
    )

    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "filer_name",
            "transaction_date",
            "transaction_type",
            "shares",
            name="uq_insider_transactions_natural_key",
        ),
        Index(
            "ix_insider_transactions_instrument_date",
            "instrument_id",
            "transaction_date",
        ),
        CheckConstraint(
            "transaction_type IN ('BUY', 'SELL', 'GIFT', 'OTHER')",
            name="ck_insider_transactions_type",
        ),
    )
