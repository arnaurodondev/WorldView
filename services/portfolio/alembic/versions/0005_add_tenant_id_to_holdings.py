"""Add tenant_id to holdings.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-07

Defence-in-depth: tenant_id is denormalised from portfolios for direct holding queries.
Primary isolation is via portfolios.get(portfolio_id, tenant_id) check in use cases.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add tenant_id as nullable first (required for backfill)
    op.add_column(
        "holdings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. Backfill tenant_id from the parent portfolio
    op.execute("UPDATE holdings h SET tenant_id = p.tenant_id FROM portfolios p WHERE h.portfolio_id = p.id")

    # 3. Enforce NOT NULL constraint now that all rows are populated
    op.alter_column("holdings", "tenant_id", nullable=False)

    # 4. Add index for tenant_id queries
    op.create_index("ix_holdings_tenant_id", "holdings", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_holdings_tenant_id", table_name="holdings")
    op.drop_column("holdings", "tenant_id")
