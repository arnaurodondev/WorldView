"""Add prediction_market_fetch_log table for Polymarket deduplication.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-09

Adds the ``prediction_market_fetch_log`` table used by the S4 PolymarketAdapter
to deduplicate market snapshots across poll cycles.  The unique index on
``(market_id, snapshot_at)`` prevents double-publishing the same market state
within a single poll window.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_market_fetch_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=True,
        ),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "resolution_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_pmfl_market_snapshot",
        "prediction_market_fetch_log",
        ["market_id", "snapshot_at"],
    )
    op.create_index(
        "ix_pmfl_source_fetched",
        "prediction_market_fetch_log",
        ["source_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pmfl_source_fetched", table_name="prediction_market_fetch_log")
    op.drop_constraint("uq_pmfl_market_snapshot", "prediction_market_fetch_log", type_="unique")
    op.drop_table("prediction_market_fetch_log")
