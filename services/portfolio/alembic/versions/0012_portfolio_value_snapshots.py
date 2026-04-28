"""Create ``portfolio_value_snapshots`` for daily value time-series.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-28

PLAN-0046 Wave 4 / T-46-4-01.

Adds the table that backs all portfolio time-series analytics (value
history, exposure, drawdown, IRR/TWR). One row per portfolio per
``snapshot_date`` — populated daily by ``PortfolioSnapshotWorker``
(non-root portfolios) and aggregated for root portfolios in the same
worker pass.

Schema notes:
    - ``UNIQUE (portfolio_id, snapshot_date)`` makes the worker idempotent:
      re-running for the same date is a no-op via ON CONFLICT DO UPDATE.
    - ``Index (portfolio_id, snapshot_date DESC)`` speeds up "last N days"
      queries which are the dominant read pattern from analytics endpoints.
    - ``cash_value`` defaults to 0 in v1 (we don't yet know broker cash).
    - ``tenant_id`` is denormalised onto each row so multi-tenant queries
      can filter without joining ``portfolios``.

Forward-compatibility (R11):
    - All columns NOT NULL with sensible defaults so the migration is safe
      to apply on a populated DB.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_value_snapshots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolios.id"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash_value", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "portfolio_id",
            "snapshot_date",
            name="uq_portfolio_value_snapshots_portfolio_date",
        ),
    )
    # Range-scan index — newest first to make latest-N-days queries cheap.
    op.create_index(
        "ix_portfolio_value_snapshots_portfolio_date_desc",
        "portfolio_value_snapshots",
        ["portfolio_id", sa.text("snapshot_date DESC")],
    )
    op.create_index(
        "ix_portfolio_value_snapshots_tenant_id",
        "portfolio_value_snapshots",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_value_snapshots_tenant_id",
        table_name="portfolio_value_snapshots",
    )
    op.drop_index(
        "ix_portfolio_value_snapshots_portfolio_date_desc",
        table_name="portfolio_value_snapshots",
    )
    op.drop_table("portfolio_value_snapshots")
