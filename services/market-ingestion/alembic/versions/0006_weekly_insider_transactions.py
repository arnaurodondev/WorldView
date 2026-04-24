"""OPT-10: Change insider_transactions polling interval from daily to weekly.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-24

Insider transaction filings are submitted on a delay (SEC Form 4 allows 2
business days after the transaction date).  Daily polling wastes ~3 EODHD
credits/day (AAPL + TSLA + AMZN) with no incremental value.  Weekly polling
(604800 s) is sufficient to capture all new filings between refreshes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Change insider_transactions from daily (86400 s) to weekly (604800 s).
    # Matches the interval already used for fundamentals (0005) and macro_indicator (0002).
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 604800, updated_at = NOW() "
            "WHERE dataset_type = 'insider_transactions' AND provider = 'eodhd'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Restore insider_transactions to daily interval.
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 86400, updated_at = NOW() "
            "WHERE dataset_type = 'insider_transactions' AND provider = 'eodhd'"
        )
    )
