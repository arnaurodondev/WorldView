"""add market_slug to prediction_markets

Revision ID: 009
Revises: 008
Create Date: 2026-04-27

WHY: Polymarket event slug is used by the frontend to construct the Polymarket
event URL (https://polymarket.com/event/{slug}). Previously the URL was always
empty because we had no slug stored. This migration adds the nullable column;
the consumer backfills it on the next poll cycle for live markets.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY nullable=True: existing rows have no slug; backfilled on next consumer
    # poll. No server_default needed — null is the correct "absent" sentinel and
    # avoids a full table rewrite (BP-126).
    op.add_column(
        "prediction_markets",
        sa.Column("market_slug", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prediction_markets", "market_slug")
