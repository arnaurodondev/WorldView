"""Add fundamental_metrics read-optimized table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-13

Introduces a narrow read-optimized projection table for fundamentals data.
One row per (instrument_id, as_of_date, metric, period_type).  Source of truth
remains the 18 section tables; this table is a derived projection populated on
write for efficient timeseries queries and screening.

Snapshot sections use last-write-wins at date-level granularity.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundamental_metrics",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id",
            UUID(as_uuid=False),
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value_numeric", sa.Numeric(24, 6), nullable=True),
        sa.Column("value_text", sa.Text, nullable=True),
        sa.Column("period_type", sa.String(20), nullable=True),
        sa.Column("section", sa.String(64), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Unique constraint: one metric value per (instrument, date, metric, period_type)
    op.create_unique_constraint(
        "uq_fundamental_metrics_instrument_date_metric",
        "fundamental_metrics",
        ["instrument_id", "as_of_date", "metric", "period_type"],
    )

    # Screening: filter by metric across instruments for a date range
    op.create_index(
        "ix_fundamental_metrics_metric_date",
        "fundamental_metrics",
        ["metric", "as_of_date"],
    )

    # Timeseries: one instrument, one metric, date range
    op.create_index(
        "ix_fundamental_metrics_instrument_metric",
        "fundamental_metrics",
        ["instrument_id", "metric", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_metrics_instrument_metric", table_name="fundamental_metrics")
    op.drop_index("ix_fundamental_metrics_metric_date", table_name="fundamental_metrics")
    op.drop_constraint("uq_fundamental_metrics_instrument_date_metric", "fundamental_metrics", type_="unique")
    op.drop_table("fundamental_metrics")
