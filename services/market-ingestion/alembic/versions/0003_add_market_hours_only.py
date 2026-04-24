"""Add market_hours_only column to polling_policies.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-19

When True, the scheduler suppresses polling outside US equity market
hours (13:30-21:00 UTC).  Saves ~1,152 API calls/day by skipping
overnight quote polling.  Defaults to False so existing policies are
unaffected until explicitly opted in.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "polling_policies",
        sa.Column(
            "market_hours_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Enable market_hours_only for all quote-type policies.
    op.execute(sa.text("UPDATE polling_policies SET market_hours_only = true WHERE dataset_type = 'quotes'"))


def downgrade() -> None:
    op.drop_column("polling_policies", "market_hours_only")
