"""Add prediction_markets and prediction_market_snapshots tables.

Revision ID: 005
Revises: 004
Create Date: 2026-04-09

Materialises incoming ``market.prediction.v1`` Kafka events into two new tables:

* ``prediction_markets`` — one row per Polymarket market (upserted on each poll);
  tracks question, outcomes metadata, and resolution status.
* ``prediction_market_snapshots`` — TimescaleDB hypertable holding one row per
  (market_id, snapshot_at) pair; stores per-outcome prices for charting/analysis.

The ``create_hypertable`` call is guarded by a TimescaleDB extension check so
the migration applies cleanly in plain Postgres environments (OQ-003 mitigation).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_markets",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'polymarket'")),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "outcomes",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("resolved_answer", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute("CREATE UNIQUE INDEX uq_prediction_markets_market_id ON prediction_markets (market_id)")
    op.execute("CREATE INDEX ix_pm_status_updated ON prediction_markets (resolution_status, updated_at DESC)")

    # Create WITHOUT inline PRIMARY KEY so that create_hypertable can succeed.
    # TimescaleDB requires every unique constraint to include the partition column
    # (snapshot_at). We add the composite PK (id, snapshot_at) after the hypertable
    # is created. On plain Postgres this composite PK is still valid and harmless.
    op.create_table(
        "prediction_market_snapshots",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "outcomes_prices",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("volume_24h", sa.Numeric(20, 4), nullable=True),
        sa.Column("liquidity", sa.Numeric(20, 4), nullable=True),
        sa.Column("source_event_id", sa.Text, nullable=False),
    )
    # Convert to TimescaleDB hypertable only if the extension is available (OQ-003 mitigation).
    # Must be done BEFORE adding any unique constraints so TimescaleDB can validate them.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
            PERFORM create_hypertable(
              'prediction_market_snapshots', 'snapshot_at',
              chunk_time_interval => INTERVAL '7 days',
              if_not_exists       => TRUE
            );
          END IF;
        END $$;
        """
    )
    # Composite PK: (id, snapshot_at) satisfies TimescaleDB's partition-column rule.
    # On plain Postgres this is equivalent to PK (id) since id is still unique.
    op.execute("ALTER TABLE prediction_market_snapshots ADD PRIMARY KEY (id, snapshot_at)")
    op.execute("CREATE UNIQUE INDEX uq_pms_market_snapshot ON prediction_market_snapshots (market_id, snapshot_at)")
    op.execute("CREATE INDEX ix_pms_market_time ON prediction_market_snapshots (market_id, snapshot_at DESC)")


def downgrade() -> None:
    op.drop_table("prediction_market_snapshots")
    op.drop_table("prediction_markets")
