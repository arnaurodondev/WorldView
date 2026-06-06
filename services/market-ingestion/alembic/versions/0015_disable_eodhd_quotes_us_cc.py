"""Disable EODHD quote polling for US and CC exchanges.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-06

PLAN-0106 Wave A-1 — Disable EODHD Quotes for US/CC.

Rationale
---------
Alpaca 1m OHLCV bars (migration 0011) provide intraday price data for all
US-exchange equities and CC-exchange crypto symbols.  Continuing to poll
EODHD for 5-minute delayed quotes on these exchanges burns API credits
redundantly and adds unnecessary load.

This migration bulk-disables all ``dataset_type='quotes'`` polling policies
for provider ``eodhd`` on exchanges ``US`` and ``CC``.

Forward-compat (R5):
    Only an UPDATE — no schema changes.  Rollback re-enables the same rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'quotes' "
            "AND exchange IN ('US', 'CC')"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'quotes' "
            "AND exchange IN ('US', 'CC')"
        )
    )
