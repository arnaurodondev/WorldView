"""Fix prediction_market_snapshots PK for TimescaleDB + add last_snapshot_at.

Revision ID: 006
Revises: 005
Create Date: 2026-04-09

Changes (D-01 — Option B):
1. Add ``last_snapshot_at TIMESTAMPTZ`` column to ``prediction_markets`` so callers
   can read the most recent snapshot time without a JOIN.  Populated retroactively
   from ``prediction_market_snapshots``.

2. Fix the ``prediction_market_snapshots`` PRIMARY KEY.  TimescaleDB requires the
   partition/time column (``snapshot_at``) to be part of every table's PRIMARY KEY.
   A single-column PK on ``id`` alone violates this constraint when the hypertable
   is present.  This migration:
   a. Drops the old single-column PK constraint.
   b. Recreates it as a composite (id, snapshot_at) — satisfying TimescaleDB.

   The UNIQUE constraint ``uq_pms_market_snapshot(market_id, snapshot_at)`` already
   exists from migration 005 and is preserved unchanged.

   In plain Postgres (no TimescaleDB), the composite PK is still valid and harmless.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add last_snapshot_at to prediction_markets (nullable — back-filled below)
    op.add_column(
        "prediction_markets",
        sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Back-fill from the most recent snapshot per market
    op.execute(
        """
        UPDATE prediction_markets pm
        SET last_snapshot_at = sub.latest
        FROM (
            SELECT market_id, MAX(snapshot_at) AS latest
            FROM prediction_market_snapshots
            GROUP BY market_id
        ) sub
        WHERE pm.market_id = sub.market_id
        """
    )

    # 2. Fix prediction_market_snapshots primary key to include snapshot_at.
    # TimescaleDB requires the partition column to appear in the PK.
    #
    # Step A: identify and drop the existing single-column PK constraint.
    # The constraint name varies by how Postgres named it (typically
    # 'prediction_market_snapshots_pkey').  Use pg_constraint to find it.
    op.execute(
        """
        DO $$
        DECLARE
          _con TEXT;
        BEGIN
          SELECT conname INTO _con
          FROM pg_constraint
          WHERE conrelid = 'prediction_market_snapshots'::regclass
            AND contype = 'p'
          LIMIT 1;

          IF _con IS NOT NULL THEN
            EXECUTE format('ALTER TABLE prediction_market_snapshots DROP CONSTRAINT %I', _con);
          END IF;
        END $$;
        """
    )

    # Step B: add composite PK (id, snapshot_at) — valid for both TimescaleDB
    # and plain Postgres.
    op.execute(
        "ALTER TABLE prediction_markets_snapshots ADD PRIMARY KEY (id, snapshot_at)"
        if False  # guard below uses the correct table name
        else "ALTER TABLE prediction_market_snapshots ADD PRIMARY KEY (id, snapshot_at)"
    )


def downgrade() -> None:
    # Revert PK to single-column (id)
    op.execute(
        """
        DO $$
        DECLARE
          _con TEXT;
        BEGIN
          SELECT conname INTO _con
          FROM pg_constraint
          WHERE conrelid = 'prediction_market_snapshots'::regclass
            AND contype = 'p'
          LIMIT 1;

          IF _con IS NOT NULL THEN
            EXECUTE format('ALTER TABLE prediction_market_snapshots DROP CONSTRAINT %I', _con);
          END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE prediction_market_snapshots ADD PRIMARY KEY (id)")

    # Remove last_snapshot_at column
    op.drop_column("prediction_markets", "last_snapshot_at")
