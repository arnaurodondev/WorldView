"""Add is_derived column to ohlcv_bars.

Revision ID: 007
Revises: 006
Create Date: 2026-04-24

Adds a boolean ``is_derived`` flag to ``ohlcv_bars`` to distinguish bars that
were computed locally (weekly/monthly aggregated from daily bars) from bars
ingested directly from an external provider.

Forward-compatible: ``server_default='false'`` means all existing rows get
``is_derived=false`` with no data loss.  The column carries a partial index on
``(instrument_id, timeframe)`` where ``is_derived = true`` to make the
``GetOrDeriveOHLCVBarsUseCase`` cache-hit query fast (PLAN-0036 W2-5).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column with a server default so the NOT NULL constraint is
    # satisfied for all existing rows without a table rewrite.
    op.add_column(
        "ohlcv_bars",
        sa.Column(
            "is_derived",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Partial index: only derived bars are looked up via find_derived().
    # Covering the timeframe column avoids a separate filter pass.
    op.create_index(
        "ix_ohlcv_bars_derived",
        "ohlcv_bars",
        ["instrument_id", "timeframe", "bar_date"],
        postgresql_where=sa.text("is_derived = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_ohlcv_bars_derived", table_name="ohlcv_bars")
    op.drop_column("ohlcv_bars", "is_derived")
