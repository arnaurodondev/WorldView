"""Add ``instruments.last_fundamentals_ingest_at`` — BP-545.

Revision ID: 021
Revises: 020
Create Date: 2026-05-26

PLAN-0096 T-W1-02 (lifted from descoped PLAN-0095 T-W1-07).

WHY THIS MIGRATION EXISTS:
  Operators (and the chat backend) need a cheap way to identify instruments
  whose fundamentals data has gone stale. The signal is already implicit on
  every successful FundamentalsConsumer cycle (logged via
  ``fundamentals_consumer.materialized``) — this column makes it queryable:

      SELECT ticker FROM instruments
       WHERE last_fundamentals_ingest_at < NOW() - INTERVAL '7 days'
         AND is_active;

  Today the only way to derive the answer is to JOIN against the section
  tables, which is O(N) per instrument and useless under load.

WHAT THIS MIGRATION DOES:
  Adds a single nullable ``TIMESTAMP WITH TIME ZONE`` column to
  ``instruments``. The consumer bumps it inside the same UoW as the section
  writes (no dual write, no outbox event — purely observational).

  Plain DDL — no CONCURRENTLY (per BP-393): additive nullable column with no
  index, runs cleanly inside the default migration transaction.

  Old rows remain NULL until the next refresh — acceptable because the column
  is observational and operator queries treat NULL as "never ingested".

DOWNGRADE: drops the column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``last_fundamentals_ingest_at`` to ``instruments``."""
    op.add_column(
        "instruments",
        sa.Column("last_fundamentals_ingest_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the freshness column."""
    op.drop_column("instruments", "last_fundamentals_ingest_at")
